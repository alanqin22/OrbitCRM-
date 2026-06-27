"""
Test Pass D (dedup_actionable) of notification_triage.

Re-emitted ACTIONABLE alerts (invoice.overdue, lead.scored, …) accumulate one
notification per recipient per emit for the SAME entity — Pass D must collapse
them to the latest one per (entity, recipient, type) while leaving a distinct
entity's alert untouched.

Non-destructive: everything runs inside one transaction with triggers disabled
(session_replication_role=replica, so the events AFTER-INSERT fan-out doesn't
fire) and is ROLLED BACK at the end. Nothing is committed.
"""
import uuid
from app.core.database import get_connection
from app.core import notification_triage as nt


def _ins_event(cur, entity_uuid, etype, ts):
    eid = uuid.uuid4()
    cur.execute(
        "INSERT INTO events (event_uuid, event_type, entity_type, entity_uuid, payload, created_at)"
        " VALUES (%s,%s,%s,%s,'{}'::jsonb, now() - (%s||' hours')::interval)",
        (str(eid), etype, "invoice" if "invoice" in etype else "lead", str(entity_uuid), ts),
    )
    return eid


def _ins_notif(cur, employee_uuid, event_uuid, ts):
    nid = uuid.uuid4()
    cur.execute(
        "INSERT INTO notifications (notification_uuid, employee_uuid, event_uuid, channel,"
        " status, title, body, metadata, created_at)"
        " VALUES (%s,%s,%s,'in_app','sent','t','b','{}'::jsonb, now() - (%s||' hours')::interval)",
        (str(nid), str(employee_uuid), str(event_uuid), ts),
    )
    return nid


def _status(cur, nid):
    cur.execute("SELECT status FROM notifications WHERE notification_uuid=%s", (str(nid),))
    return cur.fetchone()[0]


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica;")  # no trigger fan-out

            emp = uuid.uuid4()
            inv = uuid.uuid4()          # one overdue invoice, re-emitted 3x
            lead = uuid.uuid4()         # a distinct hot lead, single alert

            # 3 re-emissions of the SAME overdue invoice to the same recipient
            n_old1 = _ins_notif(cur, emp, _ins_event(cur, inv, "invoice.overdue", 72), 72)
            n_old2 = _ins_notif(cur, emp, _ins_event(cur, inv, "invoice.overdue", 48), 48)
            n_latest = _ins_notif(cur, emp, _ins_event(cur, inv, "invoice.overdue", 1), 1)
            # 1 distinct lead.scored — must survive
            n_lead = _ins_notif(cur, emp, _ins_event(cur, lead, "lead.scored", 5), 5)

            res = nt._pass_d(cur, apply=True)

            collapsed = res.get("collapsed")
            checks = [
                ("collapsed == 2", collapsed == 2),
                ("latest overdue stays unread", _status(cur, n_latest) == "sent"),
                ("older overdue #1 read", _status(cur, n_old1) == "read"),
                ("older overdue #2 read", _status(cur, n_old2) == "read"),
                ("distinct lead alert untouched", _status(cur, n_lead) == "sent"),
            ]
            for name, passed in checks:
                print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
                ok = ok and passed
        conn.rollback()  # discard all synthetic rows
    finally:
        conn.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
