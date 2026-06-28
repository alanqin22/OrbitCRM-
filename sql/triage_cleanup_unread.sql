-- ============================================================================
-- One-shot notification-backlog cleanup (manual equivalent of the scheduled
-- notification-triage sweep + an overdue de-dup the scheduler doesn't yet do).
-- Idempotent, safe to re-run on either DB. Mirrors app/core/notification_triage.
--
-- Keeps genuinely actionable, still-live alerts unread:
--   invoice.overdue (unpaid, latest per invoice+recipient), lead.scored,
--   activity.overdue_flagged, supervisor.alert.
-- Marks read: agent-inbox receipts, informational *.created/*.updated/*.completed,
--   handoff receipts, stale overdue whose invoice is now paid, and duplicate
--   re-emitted overdue alerts.
-- ============================================================================
BEGIN;

-- Pass A+B: agent-inbox receipts + informational events ----------------------
UPDATE notifications n SET read_at = now(), status = 'read'
FROM events e
WHERE n.event_uuid = e.event_uuid AND n.read_at IS NULL
  AND (
    n.channel = 'agent_inbox'
    OR e.event_type IN (
      'account.updated','contact.updated','product.updated','lead.updated',
      'account.created','contact.created','product.created','lead.created',
      'order.created','order.status_changed','order.updated',
      'opportunity.stage_changed','opportunity.updated','opportunity.created',
      'activity.completed','activity.updated','activity.created',
      'invoice_created','invoice.created','invoice_updated',
      'payment_created','payment.received','invoice_paid',
      'invoice.dunning_drafted','lead.outreach_scheduled'
    )
  );
-- agent-inbox rows with no linked event row (defensive)
UPDATE notifications SET read_at = now(), status = 'read'
WHERE read_at IS NULL AND channel = 'agent_inbox';

-- Pass C: stale overdue — invoice since paid/cancelled -----------------------
UPDATE notifications n SET read_at = now(), status = 'read'
FROM events e JOIN invoices i ON i.invoice_id = e.entity_uuid
WHERE n.event_uuid = e.event_uuid AND n.read_at IS NULL
  AND e.event_type = 'invoice.overdue'
  AND i.status IN ('paid','cancelled','void');

-- Pass D: de-dup re-emitted ACTIONABLE alerts (overdue invoices, hot leads,
-- overdue-activity nudges) — keep latest per (entity, recipient, type). --------
WITH ranked AS (
  SELECT n.notification_uuid,
         ROW_NUMBER() OVER (
           PARTITION BY e.entity_uuid, n.employee_uuid, e.event_type
           ORDER BY n.created_at DESC
         ) AS rn
  FROM notifications n
  JOIN events e ON e.event_uuid = n.event_uuid
  WHERE n.read_at IS NULL
    AND e.event_type IN ('invoice.overdue','invoice_overdue','lead.scored',
                         'activity.overdue_flagged')
)
UPDATE notifications SET read_at = now(), status = 'read'
WHERE notification_uuid IN (SELECT notification_uuid FROM ranked WHERE rn > 1);

-- Pass E (per-owner AR digest) intentionally lives in the notification_triage
-- module now (v2: ONE message per overdue-set addressed to the whole owner group,
-- self-healing). It is NOT done here to avoid recreating per-recipient AR copies.
-- Run the module's tick (or POST /notif-triage/run-once?apply=true) for AR digests.

COMMIT;

-- Report remaining unread (should be live-actionable only)
SELECT COALESCE(e.event_type,'(no event)') AS event_type, COUNT(*) AS unread
FROM notifications n LEFT JOIN events e ON e.event_uuid = n.event_uuid
WHERE n.read_at IS NULL GROUP BY 1 ORDER BY 2 DESC;
