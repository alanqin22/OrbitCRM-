"""Phase 3 supervisor test: detect KPI breaches, emit alerts, idempotency."""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPERVISOR_AUTOACT", "0")   # alert-only for the test

import psycopg2
DSN = "postgresql://postgres:aria@localhost:5434/crmdb"


def q(sql, args=None, one=False):
    c = psycopg2.connect(DSN); c.autocommit = True; cur = c.cursor()
    cur.execute(sql, args or ())
    try:
        r = cur.fetchone()[0] if one else cur.fetchall()
    except psycopg2.ProgrammingError:
        r = None
    c.close(); return r


def reset():
    ids = "(SELECT event_uuid FROM events WHERE event_type='supervisor.alert' AND source_system='supervisor' AND created_at > now()-interval '24 hours')"
    q(f"DELETE FROM notifications WHERE event_uuid IN {ids}")
    q(f"DELETE FROM event_queue  WHERE event_uuid IN {ids}")
    q("DELETE FROM events WHERE event_type='supervisor.alert' AND source_system='supervisor' AND created_at > now()-interval '24 hours'")


def main():
    from app.core import supervisor
    reset()
    print("0. reset prior supervisor alerts (24h)\n")

    # 1. Tick (force — runs even though SUPERVISOR_ENABLED may be 0)
    res = supervisor.run_supervisor_tick(force=True)
    print(f"1. tick: checked={res['checked']} breaches={res['breaches']}")
    print(f"   alerted={res['alerted']} acted={res['acted']}")
    print("\n" + res["briefing"] + "\n")

    # 2. Alerts landed on the bus (auditable + fanned out)
    n_events = q("SELECT count(*) FROM events WHERE event_type='supervisor.alert' AND source_system='supervisor' AND created_at>now()-interval '5 min'", one=True)
    n_notif = q("""SELECT count(*) FROM notifications n JOIN events e ON e.event_uuid=n.event_uuid
                   WHERE e.event_type='supervisor.alert' AND e.source_system='supervisor'
                     AND n.created_at>now()-interval '5 min'""", one=True)
    print(f"2. supervisor.alert events={n_events}, fanned-out notifications={n_notif}")

    # 3. Idempotency — a second tick within the dedupe window alerts nothing new
    res2 = supervisor.run_supervisor_tick(force=True)
    print(f"3. second tick: breaches={res2['breaches']} alerted={res2['alerted']} (expect alerted=[])")

    # 4. Payload preserved under the canonical envelope's context
    sample = q("""SELECT payload->'context'->>'rule', payload->'context'->>'severity',
                         payload->'context'->>'owner_agent'
                  FROM events WHERE event_type='supervisor.alert' AND source_system='supervisor'
                  ORDER BY created_at DESC LIMIT 1""")
    print(f"4. sample alert context: {sample[0] if sample else None}")

    ok = (len(res["breaches"]) >= 1 and res["alerted"] == res["breaches"]
          and n_events == len(res["alerted"]) and res2["alerted"] == []
          and sample and sample[0][0])
    print("\nRESULT:", "PASS ✅" if ok else "FAIL ❌")


main()
