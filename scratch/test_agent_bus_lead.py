"""End-to-end pilot #2: lead.scored (>=70) → Activity auto-outreach + Notifications.

Same consumer, queue, and governance as the invoice pilot — different event and
a different pair of cooperating agents. Pure-internal records (no external send).
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from datetime import datetime, timezone, timedelta

DSN = "postgresql://postgres:aria@localhost:5434/crmdb"
ACTIVITY_AGENT = "00000000-0000-0000-0000-000000000005"
NOTIF_AGENT    = "00000000-0000-0000-0000-000000000010"


def q(sql, args=None, one=False):
    c = psycopg2.connect(DSN); c.autocommit = True; cur = c.cursor()
    cur.execute(sql, args or ())
    try:
        r = cur.fetchone() if one else cur.fetchall()
    except psycopg2.ProgrammingError:
        r = None
    c.close(); return r


def reset():
    """Remove pilot artifacts from the last 2h (scoped to source_system='agent_bus')."""
    ids = """(SELECT event_uuid FROM events
              WHERE event_type IN ('lead.scored','lead.outreach_scheduled')
                AND source_system='agent_bus' AND created_at > now()-interval '2 hours')"""
    q(f"DELETE FROM notifications WHERE event_uuid IN {ids}")
    q(f"DELETE FROM event_queue  WHERE event_uuid IN {ids}")
    q("""DELETE FROM events WHERE event_type IN ('lead.scored','lead.outreach_scheduled')
         AND source_system='agent_bus' AND created_at > now()-interval '2 hours'""")
    q("DELETE FROM activities WHERE subject ILIKE 'Hot lead outreach%%' AND created_at > now()-interval '2 hours'")


async def main():
    import app.core.agent_bus as bus
    reset()
    print("0. reset pilot artifacts (last 2h)\n")

    n = q("SELECT fn_emit_hot_lead_events(3)", one=True)[0]
    print(f"1. emitted {n} lead.scored event(s) for Hot leads")

    pend = q("""SELECT count(*) FROM event_queue q JOIN events e ON e.event_uuid=q.event_uuid
                WHERE e.event_type='lead.scored' AND e.source_system='agent_bus' AND q.status='pending'
                  AND e.created_at > now()-interval '2 minutes'""", one=True)[0]
    a_inbox = q("""SELECT count(*) FROM notifications
                   WHERE channel='agent_inbox' AND status='pending' AND employee_uuid=%s
                     AND created_at > now()-interval '2 minutes'""", (ACTIVITY_AGENT,), one=True)[0]
    print(f"2. queue pending(lead.scored, fresh)={pend}, ActivityAgent inbox pending={a_inbox}")

    bus._CUTOFF = datetime.now(timezone.utc) - timedelta(minutes=10)
    summary = await bus.run_once()
    print(f"3. tick summary: claimed={summary['claimed']}")
    for r in summary["results"]:
        print("     →", r)

    acts = q("""SELECT subject, type, channel FROM activities
                WHERE subject ILIKE 'Hot lead outreach%%' AND created_at > now()-interval '2 minutes'
                ORDER BY created_at DESC LIMIT 5""")
    handoff = q("""SELECT count(*) FROM events
                   WHERE event_type='lead.outreach_scheduled' AND created_at > now()-interval '2 minutes'""", one=True)[0]
    notif_inbox = q("""SELECT count(*) FROM notifications
                       WHERE channel='agent_inbox' AND employee_uuid=%s
                         AND created_at > now()-interval '2 minutes'""", (NOTIF_AGENT,), one=True)[0]
    settled = q("""SELECT count(*) FROM notifications n JOIN events e ON e.event_uuid=n.event_uuid
                   WHERE e.event_type='lead.scored' AND n.channel='agent_inbox'
                     AND n.status='sent' AND n.sent_at > now()-interval '2 minutes'""", one=True)[0]
    print(f"4. outreach activities created: {[a[0]+' ['+a[1]+'/'+a[2]+']' for a in acts]}")
    print(f"   lead.outreach_scheduled events (Activity→Notifications handoff): {handoff}")
    print(f"   NotificationsAgent inbox items (scored + handoff): {notif_inbox}")
    print(f"   lead.scored agent_inbox items settled→sent: {settled}")

    dup = q("""SELECT COALESCE(max(cnt),0) FROM (
                 SELECT related_id, count(*) cnt FROM activities
                 WHERE subject ILIKE 'Hot lead outreach%%' AND created_at > now()-interval '3 days'
                 GROUP BY related_id) s""", one=True)[0]
    print(f"5. max outreach activities per lead (3d) = {dup} (expect 1, idempotent)")

    ok = (summary["claimed"] >= 1 and all(r.get("status") == "ok" for r in summary["results"])
          and len(acts) >= 1 and handoff >= 1 and notif_inbox >= 1 and settled >= 1 and dup <= 1)
    print("\nRESULT:", "PASS ✅" if ok else "FAIL ❌")


asyncio.run(main())
