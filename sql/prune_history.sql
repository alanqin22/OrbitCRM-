-- ============================================================================
-- Prune historical agent-bus / notification data to shrink the database.
--
-- The volume is dominated by notifications (fan-out history) and the events /
-- event_queue catalog. This deletes the safe-to-lose history and keeps anything
-- live or recent.
--
-- ⚠️ RECLAIMING SPACE — DO NOT `VACUUM FULL` ON A NEAR-FULL VOLUME. It rewrites
-- the table into a NEW file first (needs free scratch ≈ the table size) and will
-- crash-loop Postgres recovery with "No space left on device" if the disk is
-- tight (this happened 2026-06-27). To shrink the big table safely with ZERO
-- scratch, use TRUNCATE-and-restore instead:
--     BEGIN;
--     CREATE TEMP TABLE _keep ON COMMIT DROP AS
--       SELECT * FROM notifications WHERE read_at IS NULL;   -- rows to keep
--     TRUNCATE notifications;                                -- frees file instantly
--     INSERT INTO notifications SELECT * FROM _keep;
--     COMMIT;
-- Only `VACUUM (FULL)` the smaller tables AFTER that frees ample headroom (or
-- after resizing the volume). Plain DELETE alone just marks pages reusable.
--
-- KEEPS: all UNREAD notifications; notifications read in the last 2 days; recent
-- (<14d) pending event_queue (the live consumer worklist); recent events;
-- recent workflow history. Everything deleted is settled/old/legacy.
-- Adjust the intervals if you want to retain more/less.
-- ============================================================================
BEGIN;

-- 1) Old READ notifications (the 146 MB hog). Unread + last 2 days kept.
DELETE FROM notifications
 WHERE read_at IS NOT NULL AND read_at < now() - interval '2 days';

-- 2) Legacy workflow-engine history (migrated off n8n), older than 14 days.
DELETE FROM workflow_run_steps
 WHERE workflow_run_uuid IN (
   SELECT workflow_run_uuid FROM workflow_runs WHERE started_at < now() - interval '14 days');
DELETE FROM workflow_runs WHERE started_at < now() - interval '14 days';

-- 3) event_queue: settled rows + the legacy pending backlog (>14d never
--    reprocessed due to the consumer boot-cutoff). Recent pending is kept.
DELETE FROM event_queue WHERE status IN ('completed','superseded');
DELETE FROM event_queue WHERE status='pending' AND created_at < now() - interval '14 days';

-- 4) events older than 14 days no longer referenced by any of the 3 FK tables.
DELETE FROM events e
 WHERE e.created_at < now() - interval '14 days'
   AND NOT EXISTS (SELECT 1 FROM event_queue q   WHERE q.event_uuid = e.event_uuid)
   AND NOT EXISTS (SELECT 1 FROM notifications n  WHERE n.event_uuid = e.event_uuid)
   AND NOT EXISTS (SELECT 1 FROM workflow_runs w  WHERE w.event_uuid = e.event_uuid);

COMMIT;
