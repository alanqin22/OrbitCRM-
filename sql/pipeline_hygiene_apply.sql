-- ============================================================================
-- Pipeline hygiene — one-shot SQL equivalent of app/core/pipeline_hygiene.py
-- (used to apply on Railway, where the Python module runs against local only).
--
--   DEAD    (open, > 30d past close, idle 30d)  → closed-lost (reason logged)
--   SLIPPED (open, past close, not dead)        → re-engagement task to owner
--   + ONE Orchestrator stale-pipeline summary (refreshed, not stacked)
--
-- Idempotent: close-lost guarded by status='open'; re-engage not re-created
-- within 14d; the prior Orchestrator summary is marked read before a fresh one.
-- ============================================================================
BEGIN;

CREATE TEMP TABLE _ph_dead ON COMMIT DROP AS
SELECT o.opportunity_id, o.name, o.amount, o.owner_id, o.account_id,
       (CURRENT_DATE - o.close_date) AS days_past,
       COALESCE(NULLIF(TRIM(w.first_name||' '||w.last_name),''),'Unassigned') AS owner_name
FROM opportunities o LEFT JOIN owners w ON w.owner_id = o.owner_id
WHERE o.status='open' AND o.close_date < CURRENT_DATE - interval '30 days'
  AND NOT EXISTS (SELECT 1 FROM activities a WHERE a.related_type='opportunity'
        AND a.related_id=o.opportunity_id AND a.created_at > now()-interval '30 days');

CREATE TEMP TABLE _ph_slipped ON COMMIT DROP AS
SELECT o.opportunity_id, o.name, o.amount, o.owner_id, o.account_id,
       (CURRENT_DATE - o.close_date) AS days_past,
       COALESCE(NULLIF(TRIM(w.first_name||' '||w.last_name),''),'Unassigned') AS owner_name
FROM opportunities o LEFT JOIN owners w ON w.owner_id = o.owner_id
WHERE o.status='open' AND o.close_date < CURRENT_DATE
  AND o.opportunity_id NOT IN (SELECT opportunity_id FROM _ph_dead)
  AND NOT EXISTS (SELECT 1 FROM activities a WHERE a.related_type='opportunity'
        AND a.related_id=o.opportunity_id AND a.subject ILIKE 'Re-engage:%'
        AND a.created_at > now()-interval '14 days');

-- Opportunity agent: close-lost the dead deals
UPDATE opportunities o
   SET status='closed_lost', stage='closed_lost', updated_at=now(),
       updated_by='00000000-0000-0000-0000-000000000004'::uuid
FROM _ph_dead d WHERE o.opportunity_id=d.opportunity_id AND o.status='open';

INSERT INTO activities (type,status,subject,description,owner_id,related_type,related_id,
                        account_id,created_by,created_at,updated_at)
SELECT 'note','completed','Closed-lost (stale pipeline): '||name,
       'Auto-closed by the Opportunity agent — '||days_past||' days past close with no '
       ||'activity in 30 days. Reopen if still live.',
       owner_id,'opportunity',opportunity_id,account_id,
       '00000000-0000-0000-0000-000000000004'::uuid, now(), now()
FROM _ph_dead;

-- Activity agent: re-engagement task for slipped deals
INSERT INTO activities (type,status,subject,description,due_at,owner_id,related_type,related_id,
                        account_id,created_by,created_at,updated_at)
SELECT 'task','open','Re-engage: '||name,
       'Slipped '||days_past||' days past close date. Re-engage the buyer or re-date / '
       ||'progress the opportunity.',
       now()+interval '3 days', owner_id,'opportunity',opportunity_id,account_id,
       '00000000-0000-0000-0000-000000000005'::uuid, now(), now()
FROM _ph_slipped;

-- Orchestrator: one consolidated summary (retire the prior one first)
UPDATE notifications SET status='read', read_at=now()
WHERE employee_uuid='00000000-0000-0000-0000-000000000012'::uuid AND channel='in_app'
  AND status = ANY(ARRAY['pending','sent','unread']) AND metadata->>'kind'='pipeline_hygiene';

WITH agg AS (
  SELECT (SELECT count(*) FROM _ph_dead)                        AS nclosed,
         (SELECT COALESCE(SUM(amount),0) FROM _ph_dead)         AS amt,
         (SELECT count(*) FROM _ph_slipped)                     AS nreng,
         COALESCE(
           (SELECT ev.event_uuid FROM events ev WHERE ev.entity_type='opportunity'
              AND ev.entity_uuid IN (SELECT opportunity_id FROM _ph_dead
                                     UNION ALL SELECT opportunity_id FROM _ph_slipped) LIMIT 1),
           (SELECT event_uuid FROM events LIMIT 1))             AS anchor,
         (SELECT string_agg('- '||name||' — $'||to_char(amount,'FM999,999,990')||' · '
                            ||days_past||'d past close · owner '||owner_name, E'\n' ORDER BY amount DESC)
            FROM _ph_dead)                                      AS dead_lines,
         (SELECT string_agg('- '||name||' — $'||to_char(amount,'FM999,999,990')||' · '
                            ||days_past||'d past close · owner '||owner_name, E'\n' ORDER BY amount DESC)
            FROM _ph_slipped)                                   AS slip_lines
)
INSERT INTO notifications (employee_uuid,event_uuid,channel,status,title,body,metadata,created_at)
SELECT '00000000-0000-0000-0000-000000000012'::uuid, anchor, 'in_app', 'pending',
  '🧭 Stale-pipeline sweep — '||nclosed||' closed-lost ($'||to_char(amt,'FM999,999,990')||'), '
    ||nreng||' re-engaged',
  '### 🧭 Stale-pipeline sweep — Orchestrator coordination'||E'\n\n'||
  CASE WHEN nclosed>0 THEN '**Closed-lost '||nclosed||' dead deal(s)** ($'||to_char(amt,'FM999,999,990')
       ||' removed from pipeline):'||E'\n'||COALESCE(dead_lines,'')||E'\n\n' ELSE '' END||
  CASE WHEN nreng>0 THEN '**Re-engagement task drafted for '||nreng||' slipped deal(s)** (kept in pipeline):'
       ||E'\n'||COALESCE(slip_lines,'')||E'\n\n' ELSE '' END||
  '_Opportunity + Activity agents acted; Orchestrator summarised. Dead deals reopen if revived._',
  jsonb_build_object('kind','pipeline_hygiene','source','pipeline_hygiene_sql',
                     'closed',nclosed,'closed_amount',amt,'reengaged',nreng),
  now()
FROM agg WHERE nclosed>0 OR nreng>0;

COMMIT;
