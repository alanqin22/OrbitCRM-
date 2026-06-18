-- ============================================================================
-- supervisor.sql  —  Phase 3 (proactive supervisor) wiring
-- ============================================================================
-- Registers the 'supervisor.alert' event type the supervisor tick emits when a
-- KPI breach is detected, and subscribes the Notifications + Orchestrator agent
-- service accounts so each alert fans out to their agent_inbox. Idempotent.
-- ============================================================================

BEGIN;

-- 1. Event type (emit_event validates against the catalog)
INSERT INTO event_types (event_type, description, entity_type, is_active)
VALUES ('supervisor.alert',
        'Proactive supervisor detected a KPI breach (AR spike, slipped deals, '
        'unbilled orders, unworked leads, …)', 'system', TRUE)
ON CONFLICT (event_type) DO UPDATE SET is_active = TRUE;

-- 2. Subscriptions — Notifications(10) + Orchestrator(12) get every alert.
DELETE FROM event_subscriptions
WHERE channel = 'agent_inbox' AND event_type = 'supervisor.alert'
  AND employee_uuid IN ('00000000-0000-0000-0000-000000000010',
                        '00000000-0000-0000-0000-000000000012');

INSERT INTO event_subscriptions (employee_uuid, event_type, entity_type, channel, conditions, is_enabled)
VALUES
    ('00000000-0000-0000-0000-000000000010', 'supervisor.alert', NULL, 'agent_inbox', '{}'::jsonb, TRUE),
    ('00000000-0000-0000-0000-000000000012', 'supervisor.alert', NULL, 'agent_inbox', '{}'::jsonb, TRUE);

COMMIT;

SELECT event_type, is_active FROM event_types WHERE event_type = 'supervisor.alert';
