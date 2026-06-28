-- ============================================================================
-- Notification model v2 — one message per event, many recipients.
--
-- ROOT CAUSE of the volume blow-up: the fan-out wrote ONE full notification row
-- (title+body+payload) per subscriber per event (8-13×), so the same message was
-- copied across the whole group. New model:
--
--   notification_messages   — ONE row per event/message (the payload, stored once)
--   notification_recipients — ONE tiny row per group member (read_at, email-ready)
--
-- A VIEW `notifications` (recipient-flattened, old column shape) + INSTEAD-OF
-- INSERT/UPDATE/DELETE make the change TRANSPARENT to every existing writer:
--   • the fan-out trigger's N inserts collapse to 1 message + N recipients
--   • agent_bus digests / triage marks / retention deletes all keep working
-- Only the SP `list` mode and the dashboard count are edited (to show one-per-event).
--
-- Idempotent-ish: guarded so re-running detects the v2 shape and skips.
-- ============================================================================

DO $migrate$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_name='notification_messages' AND table_schema='public') THEN
    RAISE NOTICE 'notification_model_v2 already applied — skipping';
    RETURN;
  END IF;

  -- 1) The current per-recipient table becomes the MESSAGE table.
  ALTER TABLE notifications RENAME TO notification_messages;
  ALTER TABLE notification_messages RENAME CONSTRAINT notifications_pkey TO notification_messages_pkey;

  -- 2) Recipients (per group member) — tiny rows, email-ready.
  CREATE TABLE notification_recipients (
    recipient_uuid     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_uuid  uuid NOT NULL REFERENCES notification_messages(notification_uuid) ON DELETE CASCADE,
    employee_uuid      uuid NOT NULL,
    channel            text,
    status             text NOT NULL DEFAULT 'pending',
    read_at            timestamptz,
    sent_at            timestamptz,
    emailed_at         timestamptz,          -- future: real email delivery
    email_status       text,                 -- future: queued/sent/failed
    error_message      text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (notification_uuid, employee_uuid, channel)
  );
  CREATE INDEX ix_nrecip_emp_unread ON notification_recipients (employee_uuid) WHERE read_at IS NULL;
  CREATE INDEX ix_nrecip_msg        ON notification_recipients (notification_uuid);

  -- 3) Collapse existing rows → messages + recipients.
  --    Fan-out rows (no metadata 'kind') dedupe by event_uuid; digest/summary
  --    rows (have 'kind') stay 1:1 (they reuse anchor event_uuids).
  WITH canon AS (
    SELECT notification_uuid, employee_uuid, channel, status, read_at, sent_at, created_at, error_message,
           CASE WHEN metadata ? 'kind' THEN notification_uuid
                ELSE first_value(notification_uuid) OVER (
                       PARTITION BY event_uuid ORDER BY created_at, notification_uuid) END AS msg_id
    FROM notification_messages
  )
  INSERT INTO notification_recipients
        (notification_uuid, employee_uuid, channel, status, read_at, sent_at, created_at, error_message)
  SELECT msg_id, employee_uuid, channel, status, read_at, sent_at, created_at, error_message
  FROM canon
  ON CONFLICT (notification_uuid, employee_uuid, channel) DO NOTHING;

  -- drop the non-canonical duplicate message rows (their recipients now point at canon)
  WITH canon AS (
    SELECT notification_uuid,
           CASE WHEN metadata ? 'kind' THEN notification_uuid
                ELSE first_value(notification_uuid) OVER (
                       PARTITION BY event_uuid ORDER BY created_at, notification_uuid) END AS msg_id
    FROM notification_messages
  )
  DELETE FROM notification_messages m USING canon c
   WHERE m.notification_uuid = c.notification_uuid AND c.msg_id <> m.notification_uuid;

  -- 4) Message rows no longer carry per-recipient state — drop those columns.
  ALTER TABLE notification_messages
      DROP COLUMN employee_uuid,
      DROP COLUMN status,
      DROP COLUMN read_at,
      DROP COLUMN sent_at,
      DROP COLUMN error_message;

  -- 5) Compat VIEW (old per-recipient shape) — notification_uuid = recipient id.
  CREATE VIEW notifications AS
  SELECT r.recipient_uuid    AS notification_uuid,
         r.employee_uuid,
         m.event_uuid,
         COALESCE(r.channel, m.channel) AS channel,
         r.status,
         m.title, m.body, m.metadata,
         r.created_at,
         r.sent_at,
         r.read_at,
         r.error_message,
         m.notification_uuid AS message_uuid
  FROM notification_recipients r
  JOIN notification_messages m ON m.notification_uuid = r.notification_uuid;

  RAISE NOTICE 'notification_model_v2 applied';
END
$migrate$;

-- ── INSTEAD-OF rules so existing writers keep working transparently ──────────────
CREATE OR REPLACE FUNCTION trg_fn_notifications_ins() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE v_msg uuid;
BEGIN
  -- digest/summary rows are always their own message (they reuse anchor events);
  -- fan-out rows dedupe to one message per event.
  IF NEW.metadata ? 'kind' THEN
    INSERT INTO notification_messages (event_uuid, channel, title, body, metadata, created_at)
    VALUES (NEW.event_uuid, NEW.channel, NEW.title, NEW.body, COALESCE(NEW.metadata,'{}'::jsonb),
            COALESCE(NEW.created_at, now()))
    RETURNING notification_uuid INTO v_msg;
  ELSE
    SELECT notification_uuid INTO v_msg
      FROM notification_messages
     WHERE event_uuid = NEW.event_uuid AND NOT (metadata ? 'kind')
     ORDER BY created_at LIMIT 1;
    IF v_msg IS NULL THEN
      INSERT INTO notification_messages (event_uuid, channel, title, body, metadata, created_at)
      VALUES (NEW.event_uuid, NEW.channel, NEW.title, NEW.body, COALESCE(NEW.metadata,'{}'::jsonb),
              COALESCE(NEW.created_at, now()))
      RETURNING notification_uuid INTO v_msg;
    END IF;
  END IF;

  INSERT INTO notification_recipients
        (notification_uuid, employee_uuid, channel, status, read_at, sent_at, created_at, error_message)
  VALUES (v_msg, NEW.employee_uuid, NEW.channel, COALESCE(NEW.status,'pending'),
          NEW.read_at, NEW.sent_at, COALESCE(NEW.created_at, now()), NEW.error_message)
  ON CONFLICT (notification_uuid, employee_uuid, channel) DO NOTHING;
  RETURN NEW;
END $f$;

CREATE OR REPLACE FUNCTION trg_fn_notifications_upd() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  UPDATE notification_recipients
     SET status        = NEW.status,
         read_at       = NEW.read_at,
         sent_at       = NEW.sent_at,
         error_message = NEW.error_message,
         emailed_at    = emailed_at
   WHERE recipient_uuid = OLD.notification_uuid;
  RETURN NEW;
END $f$;

CREATE OR REPLACE FUNCTION trg_fn_notifications_del() RETURNS trigger LANGUAGE plpgsql AS $f$
DECLARE v_msg uuid;
BEGIN
  SELECT notification_uuid INTO v_msg FROM notification_recipients WHERE recipient_uuid = OLD.notification_uuid;
  DELETE FROM notification_recipients WHERE recipient_uuid = OLD.notification_uuid;
  -- garbage-collect a message with no remaining recipients
  DELETE FROM notification_messages m
   WHERE m.notification_uuid = v_msg
     AND NOT EXISTS (SELECT 1 FROM notification_recipients r WHERE r.notification_uuid = v_msg);
  RETURN OLD;
END $f$;

DROP TRIGGER IF EXISTS notifications_instead_ins ON notifications;
DROP TRIGGER IF EXISTS notifications_instead_upd ON notifications;
DROP TRIGGER IF EXISTS notifications_instead_del ON notifications;
CREATE TRIGGER notifications_instead_ins INSTEAD OF INSERT ON notifications FOR EACH ROW EXECUTE FUNCTION trg_fn_notifications_ins();
CREATE TRIGGER notifications_instead_upd INSTEAD OF UPDATE ON notifications FOR EACH ROW EXECUTE FUNCTION trg_fn_notifications_upd();
CREATE TRIGGER notifications_instead_del INSTEAD OF DELETE ON notifications FOR EACH ROW EXECUTE FUNCTION trg_fn_notifications_del();
