"""End-to-end pilot test: invoice.overdue → Accounting handler → Email handoff.

Runs the consumer in draft mode (AUTOSEND off → pure DB, no SMTP, no app needed).
"""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_BUS_AUTOSEND", "0")

import psycopg2
from datetime import datetime, timezone, timedelta

DSN = "postgresql://postgres:aria@localhost:5434/crmdb"


def q(sql, args=None, one=False):
    c = psycopg2.connect(DSN); c.autocommit = True; cur = c.cursor()
    cur.execute(sql, args or ())
    try:
        r = cur.fetchone() if one else cur.fetchall()
    except psycopg2.ProgrammingError:
        r = None
    c.close(); return r


def reset():
    """Remove pilot artifacts from the last 2h so the test is repeatable.
    Strictly scoped to source_system='agent_bus' — never touches real events."""
    ids = """(SELECT event_uuid FROM events
              WHERE event_type IN ('invoice.overdue','invoice.dunning_drafted')
                AND source_system='agent_bus' AND created_at > now()-interval '2 hours')"""
    q(f"DELETE FROM notifications WHERE event_uuid IN {ids}")
    q(f"DELETE FROM event_queue  WHERE event_uuid IN {ids}")
    q("""DELETE FROM events WHERE event_type IN ('invoice.overdue','invoice.dunning_drafted')
         AND source_system='agent_bus' AND created_at > now()-interval '2 hours'""")
    q("DELETE FROM activities WHERE subject ILIKE 'Payment reminder%%' AND created_at > now()-interval '2 hours'")


async def main():
    import app.core.agent_bus as bus
    reset()
    print("0. reset pilot artifacts (last 2h)\n")

    # 1. Emit invoice.overdue events for real overdue invoices (idempotent, capped).
    n = q("SELECT fn_emit_overdue_invoice_events(3)", one=True)[0]
    print(f"1. emitted {n} invoice.overdue event(s)")

    # 2. Confirm the bus fanned out: queue rows + AccountingAgent inbox items.
    pend = q("""SELECT count(*) FROM event_queue q JOIN events e ON e.event_uuid=q.event_uuid
                WHERE e.event_type='invoice.overdue' AND q.status='pending'
                  AND e.created_at > now()-interval '2 minutes'""", one=True)[0]
    inbox = q("""SELECT count(*) FROM notifications
                 WHERE channel='agent_inbox' AND status='pending'
                   AND employee_uuid='00000000-0000-0000-0000-000000000008'
                   AND created_at > now()-interval '2 minutes'""", one=True)[0]
    print(f"2. queue pending(invoice.overdue, fresh)={pend}, AccountingAgent inbox pending={inbox}")

    # 3. Drive one consumer tick (cutoff reaches back 10 min so we catch the emit).
    bus._CUTOFF = datetime.now(timezone.utc) - timedelta(minutes=10)
    summary = await bus.run_once()
    print(f"3. tick summary: claimed={summary['claimed']}")
    for r in summary["results"]:
        print("     →", r)

    # 4. Verify the downstream effects.
    inv = summary["results"][0].get("invoice") if summary["results"] else None
    act = q("""SELECT subject FROM activities
               WHERE subject ILIKE 'Payment reminder%%' AND created_at > now()-interval '2 minutes'
               ORDER BY created_at DESC LIMIT 3""")
    handoff = q("""SELECT count(*) FROM events
                   WHERE event_type='invoice.dunning_drafted'
                     AND created_at > now()-interval '2 minutes'""", one=True)[0]
    email_inbox = q("""SELECT count(*) FROM notifications
                       WHERE channel='agent_inbox'
                         AND employee_uuid='00000000-0000-0000-0000-000000000011'
                         AND created_at > now()-interval '2 minutes'""", one=True)[0]
    settled = q("""SELECT count(*) FROM notifications n
                   JOIN events e ON e.event_uuid=n.event_uuid
                   WHERE e.event_type='invoice.overdue' AND n.channel='agent_inbox'
                     AND n.status='sent' AND n.sent_at > now()-interval '2 minutes'""", one=True)[0]
    print(f"4. activities logged: {[a[0] for a in act]}")
    print(f"   invoice.dunning_drafted events (Accounting→Email handoff): {handoff}")
    print(f"   EmailAgent inbox items from handoff: {email_inbox}")
    print(f"   original AccountingAgent inbox items settled→sent: {settled}")

    # 5. Idempotency (no mutations): each invoice has at most ONE invoice.overdue
    #    event within the 20h guard window — the emitter never duplicates per-invoice.
    dup = q("""SELECT COALESCE(max(cnt),0) FROM (
                 SELECT entity_uuid, count(*) cnt FROM events
                 WHERE event_type='invoice.overdue' AND source_system='agent_bus'
                   AND created_at > now()-interval '20 hours'
                 GROUP BY entity_uuid) s""", one=True)[0]
    print(f"5. max invoice.overdue events per invoice (20h) = {dup} (expect 1, idempotent)")

    ok = (summary["claimed"] >= 1 and all(r.get("status") == "ok" for r in summary["results"])
          and handoff >= 1 and email_inbox >= 1 and settled >= 1 and dup <= 1)
    print("\nRESULT:", "PASS ✅" if ok else "FAIL ❌")


asyncio.run(main())
