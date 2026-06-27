"""
Test Pass F (retention) of notification_triage — non-destructive.

Inserts synthetic notifications (triggers disabled, rolled back) and verifies the
retention DELETE removes READ notifications older than NOTIF_RETENTION_DAYS while
keeping unread + recent-read ones. The table-wide DELETE on real rows is rolled
back with everything else.
"""
import uuid
from app.core.database import get_connection
from app.core import notification_triage as nt


def _exists(cur, nid):
    cur.execute("SELECT 1 FROM notifications WHERE notification_uuid=%s", (str(nid),))
    return cur.fetchone() is not None


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET session_replication_role = replica;")  # no FK/trigger noise
            ev = uuid.uuid4(); emp = uuid.uuid4()
            cur.execute(
                "INSERT INTO events (event_uuid,event_type,entity_type,entity_uuid,payload,created_at)"
                " VALUES (%s,'account.updated','account',%s,'{}'::jsonb, now())",
                (str(ev), str(uuid.uuid4())),
            )

            def mk(read_days):
                nid = uuid.uuid4()
                if read_days is None:
                    ra = "NULL"; cur.execute(
                        "INSERT INTO notifications (notification_uuid,employee_uuid,event_uuid,channel,status,title,body,metadata,created_at)"
                        " VALUES (%s,%s,%s,'in_app','sent','t','b','{}'::jsonb, now())",
                        (str(nid), str(emp), str(ev)))
                else:
                    cur.execute(
                        "INSERT INTO notifications (notification_uuid,employee_uuid,event_uuid,channel,status,title,body,metadata,created_at,read_at)"
                        " VALUES (%s,%s,%s,'in_app','read','t','b','{}'::jsonb, now(), now() - (%s||' days')::interval)",
                        (str(nid), str(emp), str(ev), read_days))
                return nid

            old_read    = mk(nt.NOTIF_RETENTION_DAYS + 5)   # past window → delete
            recent_read = mk(1)                              # within window → keep
            unread      = mk(None)                           # unread → keep

            res = nt._retention(cur, apply=True)

            checks = [
                ("retention reported deletions", res.get("notifications_deleted", 0) >= 1),
                ("old read notification deleted", not _exists(cur, old_read)),
                ("recent read notification kept", _exists(cur, recent_read)),
                ("unread notification kept", _exists(cur, unread)),
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
