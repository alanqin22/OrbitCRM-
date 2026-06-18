"""Phase 4 blackboard test: post/read/context/TTL/upsert + cross-agent
coordination (a Sales 'dunning_hold' suppresses Accounting dunning)."""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_BUS_AUTOSEND", "0")

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


async def main():
    from app.core import blackboard
    import app.core.agent_bus as bus
    ok = True

    acct = q("SELECT account_id FROM accounts WHERE COALESCE(is_deleted,false)=false LIMIT 1", one=True)
    acct = str(acct)
    blackboard.clear("account", acct)

    # 1. post + read
    blackboard.post("account", acct, "sales", "champion",
                    "CFO is our champion", {"contact": "CFO"}, 0.8, "info")
    notes = blackboard.read("account", acct)
    print(f"1. post/read -> {len(notes)} note(s); topic={notes[0]['topic']} author={notes[0]['author_agent']}")
    ok &= len(notes) == 1 and notes[0]["topic"] == "champion"

    # 2. upsert — same (entity, author, topic) updates, not duplicates
    blackboard.post("account", acct, "sales", "champion", "CFO + VP Ops now champions")
    notes = blackboard.read("account", acct, "champion")
    print(f"2. upsert -> {len(notes)} note (expect 1); note={notes[0]['note']!r}")
    ok &= len(notes) == 1 and "VP Ops" in notes[0]["note"]

    # 3. TTL — an already-expired note is not returned
    blackboard.post("account", acct, "supervisor", "stale", "old", ttl_hours=-1)
    live = [n for n in blackboard.read("account", acct) if n["topic"] == "stale"]
    print(f"3. TTL -> expired note hidden: {live == []}")
    ok &= live == []

    # 4. context() groups topics
    ctx = blackboard.context("account", acct)
    print(f"4. context -> note_count={ctx['note_count']} topics={list(ctx['topics'])}")
    ok &= "champion" in ctx["topics"]

    # 5. CROSS-AGENT: a Sales 'dunning_hold' suppresses Accounting dunning
    inv = q("""SELECT v.invoice_id FROM accounting_invoice_pipeline v
               WHERE v.payment_status IN ('unpaid','partial') AND v.due_date<CURRENT_DATE
                 AND v.computed_balance_due>50 LIMIT 1""", one=True)
    inv = str(inv)
    inv_acct = str(q("SELECT account_id FROM invoices WHERE invoice_id=%s", (inv,), one=True))
    q("DELETE FROM activities WHERE related_type='invoice' AND related_id=%s AND subject ILIKE 'Payment reminder%%'", (inv,))
    blackboard.clear("account", inv_acct, topic="dunning_hold")
    blackboard.clear("account", inv_acct, topic="ar_risk")

    blackboard.post("account", inv_acct, "sales", "dunning_hold",
                    "In contract renewal — hold dunning 7 days", {}, 0.9, "warning", 168)
    ev = {"entity_uuid": inv, "correlation_id": None}
    r_held = await bus.handle_invoice_overdue(ev)
    print(f"5a. with hold -> status={r_held['status']} reason={r_held.get('reason')!r}")
    ok &= r_held["status"] == "skipped" and "held" in (r_held.get("reason") or "")

    # remove hold -> dunning proceeds AND posts an ar_risk note to the blackboard
    blackboard.clear("account", inv_acct, topic="dunning_hold")
    r_go = await bus.handle_invoice_overdue(ev)
    ar = blackboard.read("account", inv_acct, "ar_risk")
    print(f"5b. hold cleared -> status={r_go['status']}; ar_risk note posted: {len(ar)==1}")
    ok &= r_go["status"] == "ok" and len(ar) == 1

    # 6. A2A account.context reads the shared blackboard
    from app.core import a2a
    res = await a2a.dispatch(a2a.A2ARequest(intent="account.context",
                                            params={"account_id": inv_acct}))
    print(f"6. a2a account.context -> ok={res.ok} note_count={(res.data or {}).get('note_count')}")
    ok &= res.ok and (res.data or {}).get("note_count", 0) >= 1

    # cleanup
    q("DELETE FROM activities WHERE related_type='invoice' AND related_id=%s AND subject ILIKE 'Payment reminder%%'", (inv,))
    q("DELETE FROM events WHERE source_system='agent_bus' AND event_type='invoice.dunning_drafted' AND entity_uuid=%s", (inv,))
    blackboard.clear("account", inv_acct)
    blackboard.clear("account", acct)
    print("\nRESULT:", "PASS ✅" if ok else "FAIL ❌")


asyncio.run(main())
