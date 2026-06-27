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

-- Pass E: per-owner Accounts-Receivable digest -------------------------------
-- Roll each owner's still-overdue invoices into ONE "AR summary" notification
-- and mark the individual invoice.overdue alerts read. Idempotent: skips owners
-- who already have an active AR digest. (The notification_triage module keeps
-- these refreshed/self-healing on the schedule.)
WITH ovr AS (
  SELECT n.employee_uuid AS emp, v.invoice_number AS inv,
         ROUND(v.computed_balance_due::numeric, 2) AS bal,
         (CURRENT_DATE - v.due_date::date) AS days,
         (array_agg(n.event_uuid))[1] AS anchor
  FROM notifications n
  JOIN events e ON e.event_uuid = n.event_uuid
  JOIN accounting_invoice_pipeline v ON v.invoice_id = e.entity_uuid
  WHERE n.channel='in_app' AND n.read_at IS NULL
    AND e.event_type IN ('invoice.overdue','invoice_overdue')
    AND COALESCE(n.metadata->>'kind','') NOT IN ('digest','ar_digest')
    AND v.payment_status IN ('unpaid','partial')
    AND ROUND(v.computed_balance_due::numeric, 2) > 50
  GROUP BY n.employee_uuid, v.invoice_number, bal, days
),
agg AS (
  SELECT emp, COUNT(*) AS cnt, SUM(bal) AS total, (array_agg(anchor))[1] AS anchor,
         jsonb_object_agg(inv, jsonb_build_object('balance', bal, 'days', days)) AS invoices,
         string_agg('- **'||inv||'** — $'||to_char(bal,'FM999,999,990.00')||', '||days||'d past due',
                    E'\n' ORDER BY bal DESC) AS body_lines
  FROM ovr GROUP BY emp
)
INSERT INTO notifications (employee_uuid, event_uuid, channel, status, title, body, metadata, created_at)
SELECT emp, anchor, 'in_app', 'pending',
       '💰 AR summary — '||cnt||' overdue, $'||to_char(total,'FM999,999,990')||' outstanding',
       '### 💰 Accounts-receivable summary — '||cnt||' overdue invoice(s), $'
         ||to_char(total,'FM999,999,990.00')||' outstanding'||E'\n\n'||body_lines||E'\n\n'
         ||'_Auto-summarised by the Accounting agent — one reminder per owner._',
       jsonb_build_object('kind','ar_digest','source','triage_cleanup',
                          'count',cnt,'total',total,'invoices',invoices),
       now()
FROM agg
WHERE NOT EXISTS (
  SELECT 1 FROM notifications d WHERE d.employee_uuid = agg.emp AND d.channel='in_app'
    AND d.read_at IS NULL AND d.metadata->>'kind'='ar_digest');

UPDATE notifications n SET read_at = now(), status='read'
FROM events e
WHERE n.event_uuid = e.event_uuid AND n.read_at IS NULL AND n.channel='in_app'
  AND e.event_type IN ('invoice.overdue','invoice_overdue')
  AND COALESCE(n.metadata->>'kind','') NOT IN ('digest','ar_digest');

COMMIT;

-- Report remaining unread (should be live-actionable only)
SELECT COALESCE(e.event_type,'(no event)') AS event_type, COUNT(*) AS unread
FROM notifications n LEFT JOIN events e ON e.event_uuid = n.event_uuid
WHERE n.read_at IS NULL GROUP BY 1 ORDER BY 2 DESC;
