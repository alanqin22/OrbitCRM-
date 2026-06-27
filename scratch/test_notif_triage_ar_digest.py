"""
Test Pass E (ar_digest) of notification_triage against real local data.

accounting_invoice_pipeline is a VIEW (derived from invoices/payments), so we
can't cheaply synthesize overdue rows. Instead we exercise Pass E on the live
local DB inside a transaction that is ROLLED BACK at the end — non-destructive.

Asserts: every individual invoice.overdue alert is folded away, exactly one AR
digest exists per owner who had overdue invoices, and the digests' invoice counts
add up to what was folded. Skips cleanly if there are no overdue alerts to fold.
"""
from app.core.database import get_connection
from app.core import notification_triage as nt

_RAW_OVERDUE = """
    SELECT count(*) FROM notifications n JOIN events e ON e.event_uuid = n.event_uuid
    WHERE n.channel='in_app' AND n.status = ANY(%s)
      AND e.event_type IN ('invoice.overdue','invoice_overdue')
      AND COALESCE(n.metadata->>'kind','') NOT IN ('digest','ar_digest')
"""
_AR_DIGESTS = """
    SELECT count(*), COALESCE(SUM((metadata->>'count')::int),0)
    FROM notifications
    WHERE channel='in_app' AND status = ANY(%s) AND metadata->>'kind'='ar_digest'
"""


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            unread = list(nt._UNREAD)
            cur.execute(_RAW_OVERDUE, (unread,))
            raw_before = int(cur.fetchone()[0])
            if raw_before == 0:
                print("  [SKIP] no overdue alerts present to fold")
                conn.rollback()
                print("RESULT: PASS (skipped)")
                return

            res = nt._pass_e(cur, apply=True)

            cur.execute(_RAW_OVERDUE, (unread,))
            raw_after = int(cur.fetchone()[0])
            cur.execute(_AR_DIGESTS, (unread,))
            dig_count, dig_invoices = cur.fetchone()
            dig_count = int(dig_count); dig_invoices = int(dig_invoices)

            checks = [
                ("had overdue alerts to fold", raw_before > 0),
                ("all individual overdue alerts cleared", raw_after == 0),
                ("one AR digest per owner", dig_count == res["owners"]),
                ("digest invoice counts == folded", dig_invoices == res["folded"]),
                ("folded >= owners (>=1 invoice each)", res["folded"] >= res["owners"] >= 1),
            ]
            for name, passed in checks:
                print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
                ok = ok and passed
            print(f"  (owners={res['owners']}, folded={res['folded']}, "
                  f"digests={dig_count}, digest_invoices={dig_invoices})")

            # Idempotency: a second apply should fold nothing new and keep one digest/owner.
            res2 = nt._pass_e(cur, apply=True)
            cur.execute(_AR_DIGESTS, (unread,))
            dig_count2 = int(cur.fetchone()[0])
            idem = (res2["folded"] == 0 and dig_count2 == dig_count)
            print(f"  [{'PASS' if idem else 'FAIL'}] idempotent re-run (folded={res2['folded']}, digests={dig_count2})")
            ok = ok and idem
        conn.rollback()  # discard everything
    finally:
        conn.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
