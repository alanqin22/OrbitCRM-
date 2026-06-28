"""
Test Pass F (retention) of notification_triage against the v2 model — non-destructive.

Setup writes base rows (notification_messages + notification_recipients) with
triggers suppressed (no fan-out / FK noise), then RE-ENABLES triggers so the
triage's view operations (INSTEAD-OF DELETE) fire normally. Rolled back.
"""
import uuid
from app.core.database import get_connection
from app.core import notification_triage as nt


def _recip_exists(cur, rid):
    cur.execute("SELECT 1 FROM notification_recipients WHERE recipient_uuid=%s", (str(rid),))
    return cur.fetchone() is not None


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica;")  # quiet setup
            emp = uuid.uuid4()

            def mk(read_days):
                # one message per recipient (model: one recipient per message+employee+channel)
                ev = uuid.uuid4(); msg = uuid.uuid4(); rid = uuid.uuid4()
                cur.execute(
                    "INSERT INTO events (event_uuid,event_type,entity_type,entity_uuid,payload,created_at)"
                    " VALUES (%s,'account.updated','account',%s,'{}'::jsonb, now())",
                    (str(ev), str(uuid.uuid4())))
                cur.execute(
                    "INSERT INTO notification_messages (notification_uuid,event_uuid,channel,title,body,metadata,created_at)"
                    " VALUES (%s,%s,'in_app','t','b','{}'::jsonb, now())", (str(msg), str(ev)))
                if read_days is None:
                    cur.execute(
                        "INSERT INTO notification_recipients (recipient_uuid,notification_uuid,employee_uuid,channel,status,created_at)"
                        " VALUES (%s,%s,%s,'in_app','sent', now())", (str(rid), str(msg), str(emp)))
                else:
                    cur.execute(
                        "INSERT INTO notification_recipients (recipient_uuid,notification_uuid,employee_uuid,channel,status,created_at,read_at)"
                        " VALUES (%s,%s,%s,'in_app','read', now(), now() - (%s||' days')::interval)",
                        (str(rid), str(msg), str(emp), read_days))
                return rid

            old_read    = mk(nt.NOTIF_RETENTION_DAYS + 5)   # past window → delete
            recent_read = mk(1)                              # within window → keep
            unread      = mk(None)                           # unread → keep

            cur.execute("SET session_replication_role = DEFAULT;")  # triage uses the view
            res = nt._retention(cur, apply=True)

            checks = [
                ("retention reported deletions", res.get("notifications_deleted", 0) >= 1),
                ("old read recipient deleted", not _recip_exists(cur, old_read)),
                ("recent read recipient kept", _recip_exists(cur, recent_read)),
                ("unread recipient kept", _recip_exists(cur, unread)),
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
