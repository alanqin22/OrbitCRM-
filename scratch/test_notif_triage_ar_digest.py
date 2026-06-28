"""
Test Pass E (ar_digest) of notification_triage — v2 group-message behavior.

Three owners each get unread invoice.overdue alerts for the SAME real overdue
invoices. Pass E must fold them into ONE ar_digest MESSAGE addressed to all three
recipients (not three identical copies). Setup writes base rows with triggers
suppressed, re-enables for the pass, and rolls back — non-destructive.
"""
import uuid
from app.core.database import get_connection
from app.core import notification_triage as nt


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            # two real overdue invoices to fold
            cur.execute("""SELECT invoice_id, invoice_number FROM accounting_invoice_pipeline
                           WHERE payment_status IN ('unpaid','partial')
                             AND ROUND(computed_balance_due::numeric,2) > %s
                             AND (CURRENT_DATE - due_date::date) > 0
                           LIMIT 2""", (nt.MATERIAL_BALANCE,))
            invs = cur.fetchall()
            if len(invs) < 1:
                print("  [SKIP] no overdue invoices to fold"); conn.rollback()
                print("RESULT: PASS (skipped)"); return

            cur.execute("SET session_replication_role = replica;")
            emps = [uuid.uuid4() for _ in range(3)]   # three owners, same invoice set
            for inv_id, inv_no in invs:
                ev = uuid.uuid4(); msg = uuid.uuid4()
                cur.execute("INSERT INTO events (event_uuid,event_type,entity_type,entity_uuid,payload,created_at)"
                            " VALUES (%s,'invoice.overdue','invoice',%s,'{}'::jsonb, now())", (str(ev), str(inv_id)))
                cur.execute("INSERT INTO notification_messages (notification_uuid,event_uuid,channel,title,body,metadata,created_at)"
                            " VALUES (%s,%s,'in_app','raw','b','{}'::jsonb, now())", (str(msg), str(ev)))
                for e in emps:
                    cur.execute("INSERT INTO notification_recipients (notification_uuid,employee_uuid,channel,status,created_at)"
                                " VALUES (%s,%s,'in_app','sent', now())", (str(msg), str(e)))
            cur.execute("SET session_replication_role = DEFAULT;")

            res = nt._pass_e(cur, apply=True)

            # exactly one ar_digest message, addressed to all 3 owners
            cur.execute("SELECT notification_uuid FROM notification_messages WHERE metadata->>'kind'='ar_digest'")
            msgs = cur.fetchall()
            n_recip = 0
            if len(msgs) == 1:
                cur.execute("SELECT COUNT(*) FROM notification_recipients WHERE notification_uuid=%s", (msgs[0][0],))
                n_recip = int(cur.fetchone()[0])

            checks = [
                ("pass folded the overdue", res.get("folded", 0) >= 1),
                ("exactly ONE ar_digest message", len(msgs) == 1),
                ("message addressed to all 3 owners", n_recip == 3),
                ("one group (shared overdue set)", res.get("groups") == 1),
            ]
            for name, passed in checks:
                print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
                ok = ok and passed
            print(f"  (owners={res.get('owners')}, folded={res.get('folded')}, "
                  f"messages={len(msgs)}, recipients={n_recip})")
        conn.rollback()
    finally:
        conn.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
