"""Phase 2 A2A test: registry, resolution, dry-run, NL dispatch, structured
(non-NL) input contract, and orchestrator capability routing."""
import asyncio, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    from app.core import a2a
    ok_all = True

    # 1. Capability manifest (discoverable)
    m = a2a.manifest()
    print(f"1. manifest: {m['count']} capabilities across {len(m['by_agent'])} agents; "
          f"structured={[c['intent'] for c in m['capabilities'] if c['structured']]}")
    ok_all &= m["count"] >= 6

    # 2. Capability-based resolution
    ok_all &= a2a.resolve("accounting.summary").agent == "accounting"
    ok_all &= a2a.resolve("bogus.intent") is None
    ok_all &= a2a.resolve("accounting.summary", to_agent="email") is None
    print("2. resolution: intent→agent + to_agent pinning OK")

    # 3. Dry-run (no side effect) — note it reports the structured route
    dr = await a2a.dispatch(a2a.A2ARequest(intent="leads.list", params={"scoreMin": 70}),
                            dry_run=True)
    print(f"3. dry-run: '{dr.output}'")
    ok_all &= dr.ok and "structured" in dr.output

    # 4. STRUCTURED input contract — typed params → structured DATA (no NL/AI)
    s1 = await a2a.dispatch(a2a.A2ARequest(from_agent="test", intent="leads.list",
                                           params={"scoreMin": 70, "pageSize": 5}))
    recs = (s1.data or {}).get("records") or (s1.data or {}).get("leads") or []
    print(f"4a. leads.list scoreMin=70 (structured) -> ok={s1.ok} records={len(recs)} "
          f"scores={[r.get('score') for r in recs[:5]]}")
    ok_all &= s1.ok and s1.data is not None and all((r.get("score") or 0) >= 70 for r in recs)
    s2 = await a2a.dispatch(a2a.A2ARequest(intent="accounting.summary"))
    print(f"4b. accounting.summary (structured)      -> ok={s2.ok} data?={s2.data is not None} '{s2.output}'")
    ok_all &= s2.ok and s2.data is not None

    # 4c. wider structured coverage
    for it in ("orders.sales_summary", "contacts.list", "opportunities.pipeline",
               "products.low_stock"):
        rr = await a2a.dispatch(a2a.A2ARequest(intent=it))
        print(f"4c. {it:28} (structured) -> ok={rr.ok} data?={rr.data is not None}")
        ok_all &= rr.ok and rr.data is not None

    # 5. prose=True forces the NL/agent path (formatted output)
    p1 = await a2a.dispatch(a2a.A2ARequest(intent="leads.list", prose=True))
    print(f"5. prose path -> ok={p1.ok} markdown={'Lead' in (p1.output or '')}")
    ok_all &= p1.ok and "Lead" in (p1.output or "")

    # 6. Correlation lineage
    cid = "11111111-1111-1111-1111-111111111111"
    r3 = await a2a.dispatch(a2a.A2ARequest(intent="accounting.summary", correlation_id=cid))
    ok_all &= r3.correlation_id == cid
    print(f"6. correlation carried through: {r3.correlation_id == cid}")

    # 6b. PEER HANDOFF — composite capability delegates to peers + composes
    comp = await a2a.dispatch(a2a.A2ARequest(from_agent="test", intent="crm.pipeline_snapshot"))
    print(f"6b. crm.pipeline_snapshot (peer handoff) -> ok={comp.ok} hops={comp.hops} "
          f"keys={list((comp.data or {}).keys())}")
    ok_all &= (comp.ok and comp.hops == ["accounting.summary", "leads.list"]
               and "financials" in (comp.data or {}))

    # 6c. NEGOTIATION — unknown intent returns closest suggestions
    neg = await a2a.dispatch(a2a.A2ARequest(intent="lead.list"))   # typo: singular
    sugg = (neg.data or {}).get("suggestions") or []
    print(f"6c. negotiation 'lead.list' -> ok={neg.ok} suggestions={sugg}")
    ok_all &= (not neg.ok) and "leads.list" in sugg

    # 7. Orchestrator capability routing (in-process)
    import httpx
    from app.main import app as _app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app),
                                 base_url="http://t") as cli:
        man = (await cli.post("/orchestrator-chat",
               json={"sessionId": "t", "chatInput": {"message": "capabilities"}})).json()
        print(f"7a. orch 'capabilities' -> mode={man.get('mode')}")
        ok_all &= man.get("mode") == "a2a_manifest"
        rt = (await cli.post("/orchestrator-chat",
              json={"sessionId": "t",
                    "chatInput": {"message": "route: leads.list scoreMin=70"}})).json()
        print(f"7b. orch 'route: leads.list scoreMin=70' -> mode={rt.get('mode')} "
              f"ok={rt.get('success')}")
        ok_all &= rt.get("mode") == "a2a" and rt.get("success")
        # write capability is dry-run by default (safety)
        wr = (await cli.post("/orchestrator-chat",
              json={"sessionId": "t",
                    "chatInput": {"message": "route: email.send_payment_reminder to=x@y.com"}})).json()
        print(f"7c. orch write w/o confirm -> dry-run={'dry-run' in (wr.get('output') or '')}")
        ok_all &= "dry-run" in (wr.get("output") or "")
        cp = (await cli.post("/orchestrator-chat",
              json={"sessionId": "t",
                    "chatInput": {"message": "route: crm.pipeline_snapshot"}})).json()
        print(f"7d. orch 'route: crm.pipeline_snapshot' -> mode={cp.get('mode')} ok={cp.get('success')}")
        ok_all &= cp.get("mode") == "a2a" and cp.get("success")
        # 7e. single-agent NL query now routes through the A2A layer (primary path)
        sa = (await cli.post("/orchestrator-chat",
              json={"sessionId": "t", "chatInput": {"message": "show leads in Toronto"}})).json()
        print(f"7e. orch single-agent 'show leads in Toronto' -> routedVia={sa.get('routedVia')} "
              f"routedTo={sa.get('routedTo')}")
        ok_all &= sa.get("routedVia") == "a2a:leads.query"

    print("\nRESULT:", "PASS ✅" if ok_all else "FAIL ❌")


asyncio.run(main())
