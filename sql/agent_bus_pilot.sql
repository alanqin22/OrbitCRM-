-- ============================================================================
-- AGENT BUS — Phase 1 pilot wiring:  overdue invoice → Accounting → Email
-- ============================================================================
-- Idempotent. Adds exactly what the pilot needs on top of the existing bus
-- (events / event_queue / event_subscriptions / trg_fn_events_after_insert /
--  emit_event), and NOTHING else:
--
--   1. Subscribe the Accounting + Email + Notifications agent service accounts
--      to the canonical dotted event types the pilot uses.
--   2. fn_emit_overdue_invoice_events(p_max) — detect materially-overdue
--      invoices that have NOT been emitted recently and emit_event('invoice.overdue').
--
-- The dotted 'invoice.overdue' type has ~0 historical backlog (the 1,554 stale
-- rows are the legacy underscore 'invoice_overdue', which the consumer ignores),
-- so turning the consumer on can never replay ancient events.
-- ============================================================================

BEGIN;

-- 0. Register the event types the handlers emit (emit_event validates against
--    the event_types catalog). 'invoice.overdue' is already registered;
--    'lead.scored' is emitted today by trgfn_lead_events (direct insert) but was
--    never cataloged — register it so emit_event() may use it too.
INSERT INTO event_types (event_type, description, entity_type, is_active)
VALUES
    ('invoice.dunning_drafted',
     'Accounting agent drafted/sent an overdue-invoice payment reminder', 'invoice', TRUE),
    ('lead.scored',
     'Lead was (re)scored by fn_score_lead', 'lead', TRUE),
    ('lead.outreach_scheduled',
     'Activity agent scheduled auto-outreach for a hot lead', 'lead', TRUE)
ON CONFLICT (event_type) DO UPDATE SET is_active = TRUE;

-- 1. Subscriptions ----------------------------------------------------------
-- AccountingAgent(08) owns the reaction; EmailAgent(11) receives the handoff;
-- NotificationsAgent(10) keeps an audit copy.
DELETE FROM event_subscriptions
WHERE channel = 'agent_inbox'
  AND event_type IN ('invoice.overdue', 'invoice.dunning_drafted')
  AND employee_uuid IN (
      '00000000-0000-0000-0000-000000000008',
      '00000000-0000-0000-0000-000000000010',
      '00000000-0000-0000-0000-000000000011');

INSERT INTO event_subscriptions (employee_uuid, event_type, entity_type, channel, conditions, is_enabled)
VALUES
    ('00000000-0000-0000-0000-000000000008', 'invoice.overdue',         'invoice', 'agent_inbox', '{}'::jsonb, TRUE),
    ('00000000-0000-0000-0000-000000000010', 'invoice.overdue',         'invoice', 'agent_inbox', '{}'::jsonb, TRUE),
    ('00000000-0000-0000-0000-000000000011', 'invoice.dunning_drafted', 'invoice', 'agent_inbox', '{}'::jsonb, TRUE);

-- ── Pilot #2:  lead.scored (≥70 = Hot) → Activity auto-outreach + Notifications
-- ActivityAgent(05) owns the reaction; NotificationsAgent(10) receives both the
-- scored signal and the outreach-scheduled handoff. LeadAgent(01) already subs
-- lead.scored from the base seed.
DELETE FROM event_subscriptions
WHERE channel = 'agent_inbox'
  AND event_type IN ('lead.scored', 'lead.outreach_scheduled')
  AND employee_uuid IN (
      '00000000-0000-0000-0000-000000000005',
      '00000000-0000-0000-0000-000000000010');

INSERT INTO event_subscriptions (employee_uuid, event_type, entity_type, channel, conditions, is_enabled)
VALUES
    ('00000000-0000-0000-0000-000000000005', 'lead.scored',             'lead', 'agent_inbox', '{}'::jsonb, TRUE),
    ('00000000-0000-0000-0000-000000000010', 'lead.scored',             'lead', 'agent_inbox', '{}'::jsonb, TRUE),
    ('00000000-0000-0000-0000-000000000010', 'lead.outreach_scheduled', 'lead', 'agent_inbox', '{}'::jsonb, TRUE);

-- 2. Overdue-invoice event emitter -----------------------------------------
-- Emits 'invoice.overdue' for materially past-due invoices that have not had an
-- overdue event in the last 20h (so a daily run is idempotent). Returns count.
CREATE OR REPLACE FUNCTION fn_emit_overdue_invoice_events(p_max int DEFAULT 200)
RETURNS integer AS $$
DECLARE
    v_rec   record;
    v_count int := 0;
BEGIN
    FOR v_rec IN
        SELECT v.invoice_id, v.invoice_number, v.account_id, v.contact_id,
               ROUND(v.computed_balance_due::numeric, 2) AS balance,
               (CURRENT_DATE - v.due_date::date)         AS days_overdue
        FROM   accounting_invoice_pipeline v
        WHERE  v.payment_status IN ('unpaid', 'partial')
          AND  v.due_date < CURRENT_DATE
          AND  v.computed_balance_due > 50
          AND  NOT EXISTS (
                   SELECT 1 FROM events e
                   WHERE  e.event_type = 'invoice.overdue'
                     AND  e.entity_uuid = v.invoice_id
                     AND  e.created_at > now() - interval '20 hours')
        ORDER  BY (CURRENT_DATE - v.due_date::date) DESC
        LIMIT  p_max
    LOOP
        PERFORM emit_event(
            'invoice.overdue', 'invoice', v_rec.invoice_id,
            jsonb_build_object(
                'invoice_number', v_rec.invoice_number,
                'account_id',     v_rec.account_id,
                'contact_id',     v_rec.contact_id,
                'balance',        v_rec.balance,
                'days_overdue',   v_rec.days_overdue),
            NULL, 'agent_bus');
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_emit_overdue_invoice_events(int) IS
    'Agent-bus Phase 1: emits invoice.overdue events for materially past-due '
    'invoices not emitted in the last 20h. Idempotent; cap via p_max.';

-- 3. Hot-lead event emitter -------------------------------------------------
-- Emits 'lead.scored' for Hot leads (score >= 70) that are still open and have
-- not had a pilot-emitted lead.scored event in the last 20h. In production the
-- lead-scoring SP emits lead.scored on every rescore; this is the demo trigger.
CREATE OR REPLACE FUNCTION fn_emit_hot_lead_events(p_max int DEFAULT 100)
RETURNS integer AS $$
DECLARE
    v_rec   record;
    v_count int := 0;
BEGIN
    FOR v_rec IN
        SELECT l.lead_id, l.first_name, l.last_name, l.company, l.score, l.owner_id
        FROM   leads l
        WHERE  l.score >= 70
          AND  COALESCE(l.converted, false) = false
          AND  COALESCE(l.is_deleted, false) = false
          AND  COALESCE(l.status, '') NOT IN ('disqualified', 'converted')
          AND  NOT EXISTS (
                   SELECT 1 FROM events e
                   WHERE  e.event_type   = 'lead.scored'
                     AND  e.entity_uuid  = l.lead_id
                     AND  e.source_system = 'agent_bus'
                     AND  e.created_at > now() - interval '20 hours')
        ORDER  BY l.score DESC
        LIMIT  p_max
    LOOP
        PERFORM emit_event(
            'lead.scored', 'lead', v_rec.lead_id,
            jsonb_build_object(
                'first_name', v_rec.first_name,
                'last_name',  v_rec.last_name,
                'company',    v_rec.company,
                'score',      v_rec.score,
                'owner_id',   v_rec.owner_id),
            NULL, 'agent_bus');
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fn_emit_hot_lead_events(int) IS
    'Agent-bus Phase 1: emits lead.scored for Hot (>=70) open leads not emitted '
    'in the last 20h. Idempotent; cap via p_max.';

COMMIT;

-- Verify -------------------------------------------------------------------
SELECT employee_uuid, event_type
FROM   event_subscriptions
WHERE  channel = 'agent_inbox'
  AND  event_type IN ('invoice.overdue', 'invoice.dunning_drafted',
                      'lead.scored', 'lead.outreach_scheduled')
ORDER  BY event_type, employee_uuid;
