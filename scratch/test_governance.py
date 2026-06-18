"""Phase 5 governance test: confidence-gating (act/propose/skip), approval
queue, approve→execute, reject. No real sends (execute is stubbed)."""
import os, asyncio, sys, uuid
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GOV_ENABLED"] = "1"          # turn gating on for the test
os.environ.setdefault("AGENT_BUS_AUTOSEND", "0")

import psycopg2
DSN = "postgresql://postgres:aria@localhost:5434/crmdb"


def q(sql, args=None):
    c = psycopg2.connect(DSN); c.autocommit = True; cur = c.cursor()
    cur.execute(sql, args or ())
    c.close()


async def main():
    from app.core import governance, a2a
    ok = True
    print(f"governance: enabled={governance.ENABLED} act_min={governance.ACT_MIN} "
          f"propose_min={governance.PROPOSE_MIN}")

    # 1. Policy
    decisions = (governance.decide(0.9), governance.decide(0.6), governance.decide(0.3))
    print(f"1. decide(0.9/0.6/0.3) = {decisions}")
    ok &= decisions == ("act", "propose", "skip")

    inv = str(uuid.uuid4())
    # 2. Medium-confidence WRITE → PROPOSED (queued, NOT executed)
    prop = await a2a.dispatch(a2a.A2ARequest(
        from_agent="accounting", intent="email.send_payment_reminder",
        entity=a2a.EntityRef("invoice", inv),
        params={"to": "x@y.com", "invoice_number": "INV-GOV"}, confidence=0.6))
    aid = (prop.data or {}).get("approval_uuid")
    print(f"2. write conf=0.6 -> ok={prop.ok} status={(prop.data or {}).get('status')} aid={str(aid)[:8]}")
    ok &= prop.ok and aid and (prop.data or {}).get("status") == "pending_approval"

    # 3. Low-confidence WRITE → SKIPPED
    skip = await a2a.dispatch(a2a.A2ARequest(
        intent="email.send_payment_reminder", params={"to": "x@y.com"}, confidence=0.3))
    print(f"3. write conf=0.3 -> ok={skip.ok} error={skip.error!r}")
    ok &= (not skip.ok) and "skipped by governance" in (skip.error or "")

    # 4. Queue shows the pending proposal
    pend = governance.pending()
    print(f"4. queue pending={len(pend)}; contains our proposal: {any(p['approval_uuid']==aid for p in pend)}")
    ok &= any(p["approval_uuid"] == aid for p in pend)

    # 5. Reject a second proposal
    prop2 = await a2a.dispatch(a2a.A2ARequest(
        intent="email.send_payment_reminder", params={"to": "z@y.com"}, confidence=0.6))
    aid2 = (prop2.data or {}).get("approval_uuid")
    rej = governance.reject(aid2, "tester", "not now")
    print(f"5. reject -> {rej}")
    ok &= rej["ok"] and rej["status"] == "rejected"

    # 6. Approve → execute (stub dispatch so nothing is actually sent)
    calls = []
    async def _stub(req):
        calls.append(req)
        return a2a.A2AResult(True, req.intent, "email", "cid", output="[stub] executed")
    orig = a2a.dispatch
    a2a.dispatch = _stub
    try:
        appr = await governance.approve(aid, "manager", "ok to send")
    finally:
        a2a.dispatch = orig
    row = governance._row(aid)
    print(f"6. approve -> ok={appr['ok']} final_status={row['status']} "
          f"stub_called={len(calls)} bypass={calls[0].govern_bypass if calls else None}")
    ok &= (appr["ok"] and row["status"] == "executed"
           and len(calls) == 1 and calls[0].govern_bypass is True)

    # cleanup
    q("DELETE FROM action_approvals WHERE action_type='email.send_payment_reminder' AND created_at > now()-interval '10 min'")
    print("\nRESULT:", "PASS ✅" if ok else "FAIL ❌")


asyncio.run(main())
