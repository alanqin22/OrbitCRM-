"""
Test Pass D (dedup_actionable) of notification_triage against the v2 model.

Re-emitted ACTIONABLE alerts for the SAME entity must collapse to the latest per
(entity, recipient, type); a distinct entity is untouched. Setup writes base rows
(events + notification_messages + notification_recipients) with triggers
suppressed, then re-enables them so Pass D's view UPDATE (INSTEAD-OF) fires.
Rolled back — non-destructive.
"""
import uuid
from app.core.database import get_connection
from app.core import notification_triage as nt


def _status(cur, rid):
    cur.execute("SELECT status FROM notification_recipients WHERE recipient_uuid=%s", (str(rid),))
    row = cur.fetchone()
    return row[0] if row else None


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica;")  # quiet setup
            emp = uuid.uuid4()
            inv = uuid.uuid4()      # one overdue invoice, re-emitted 3x
            lead = uuid.uuid4()     # a distinct hot lead

            def mk(entity, etype, hours):
                ev = uuid.uuid4(); msg = uuid.uuid4(); rid = uuid.uuid4()
                cur.execute(
                    "INSERT INTO events (event_uuid,event_type,entity_type,entity_uuid,payload,created_at)"
                    " VALUES (%s,%s,%s,%s,'{}'::jsonb, now() - (%s||' hours')::interval)",
                    (str(ev), etype, 'invoice' if 'invoice' in etype else 'lead', str(entity), hours))
                cur.execute(
                    "INSERT INTO notification_messages (notification_uuid,event_uuid,channel,title,body,metadata,created_at)"
                    " VALUES (%s,%s,'in_app','t','b','{}'::jsonb, now() - (%s||' hours')::interval)",
                    (str(msg), str(ev), hours))
                cur.execute(
                    "INSERT INTO notification_recipients (recipient_uuid,notification_uuid,employee_uuid,channel,status,created_at)"
                    " VALUES (%s,%s,%s,'in_app','sent', now() - (%s||' hours')::interval)",
                    (str(rid), str(msg), str(emp), hours))
                return rid

            r_old1   = mk(inv,  'invoice.overdue', 72)
            r_old2   = mk(inv,  'invoice.overdue', 48)
            r_latest = mk(inv,  'invoice.overdue', 1)
            r_lead   = mk(lead, 'lead.scored',     5)

            cur.execute("SET session_replication_role = DEFAULT;")  # Pass D uses the view
            res = nt._pass_d(cur, apply=True)

            checks = [
                ("collapsed == 2", res.get("collapsed") == 2),
                ("latest overdue stays unread", _status(cur, r_latest) in ('pending','sent','unread')),
                ("older overdue #1 read", _status(cur, r_old1) == 'read'),
                ("older overdue #2 read", _status(cur, r_old2) == 'read'),
                ("distinct lead alert untouched", _status(cur, r_lead) in ('pending','sent','unread')),
            ]
            for name, passed in checks:
                print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
                ok = ok and passed
        conn.rollback()
    finally:
        conn.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
