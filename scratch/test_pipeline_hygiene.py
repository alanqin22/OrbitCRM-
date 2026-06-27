"""
Test pipeline_hygiene cooperation against real local data, rolled back.

Exercises the internal steps (classify → close-lost dead → re-engage slipped →
Orchestrator summary) inside one transaction that is ROLLED BACK — non-destructive.
Skips cleanly if there are no past-close open deals.
"""
from app.core.database import get_connection
from app.core import pipeline_hygiene as ph


def main():
    conn = get_connection()
    ok = True
    try:
        with conn.cursor() as cur:
            deals = ph._slipped_deals(cur)
            if not deals:
                print("  [SKIP] no past-close open deals present")
                conn.rollback(); print("RESULT: PASS (skipped)"); return

            dead = [d for d in deals if d["dead"]]
            slipped = [d for d in deals if not d["dead"]]
            print(f"  (slipped_total={len(deals)}, dead={len(dead)}, slipped={len(slipped)})")

            checks = [("found past-close deals", len(deals) > 0)]

            # Close-lost the dead ones
            closed = [d for d in dead if ph._close_lost(cur, d)]
            checks.append(("all dead deals closed-lost", len(closed) == len(dead)))
            if dead:
                cur.execute("SELECT status, stage FROM opportunities WHERE opportunity_id=%s::uuid",
                            (dead[0]["opportunity_id"],))
                st, stg = cur.fetchone()
                checks.append(("dead deal now closed_lost", st == "closed_lost" and stg == "closed_lost"))
                # idempotent: a second close returns False (no longer open)
                checks.append(("close-lost idempotent", ph._close_lost(cur, dead[0]) is False))
                cur.execute("""SELECT count(*) FROM activities WHERE related_type='opportunity'
                               AND related_id=%s::uuid AND subject ILIKE 'Closed-lost%%'""",
                            (dead[0]["opportunity_id"],))
                checks.append(("close logged an activity", int(cur.fetchone()[0]) >= 1))

            # Re-engage the slipped ones
            reng = [d for d in slipped if ph._reengage(cur, d)]
            if slipped:
                checks.append(("re-engage tasks created", len(reng) >= 1))
                cur.execute("""SELECT count(*) FROM activities WHERE related_type='opportunity'
                               AND related_id=%s::uuid AND subject ILIKE 'Re-engage:%%' AND status='open'""",
                            (slipped[0]["opportunity_id"],))
                checks.append(("slipped deal has a re-engage task", int(cur.fetchone()[0]) >= 1))
                # idempotent within 14d
                checks.append(("re-engage idempotent", ph._reengage(cur, slipped[0]) is False))

            # Orchestrator summary
            anchor = next((d["anchor"] for d in deals if d.get("anchor")), None)
            if (closed or reng) and anchor:
                ph._post_summary(cur, closed, reng, anchor)
                cur.execute("""SELECT count(*) FROM notifications WHERE employee_uuid=%s::uuid
                               AND metadata->>'kind'='pipeline_hygiene' AND status = ANY(%s)""",
                            (ph.ORCH_AGENT, ["pending", "sent", "unread"]))
                checks.append(("one orchestrator summary posted", int(cur.fetchone()[0]) == 1))

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
