"""End-to-end live smoke test of the agent-cooperation stack, Phase 1 → 5,
against the running server (http://127.0.0.1:8000). Cleans up after itself."""
import requests, psycopg2, sys, uuid
sys.stdout.reconfigure(encoding="utf-8")
B = "http://127.0.0.1:8000"
DSN = "postgresql://postgres:aria@localhost:5434/crmdb"


def sql(q, args=None, fetch=False):
    c = psycopg2.connect(DSN); c.autocommit = True; cur = c.cursor()
    cur.execute(q, args)          # args=None → no %-formatting (literal % in ILIKE ok)
    r = cur.fetchall() if fetch else None
    c.close(); return r


def gj(p): return requests.get(B + p, timeout=30).json()
def pj(p, body=None): return requests.post(B + p, json=body or {}, timeout=90).json()


PASS = []


def check(label, cond):
    PASS.append(bool(cond))
    print(f"   {'✅' if cond else '❌'} {label}")


# ── PHASE 1 — event bus + autonomous consumer ──────────────────────────────
print("PHASE 1 — Event bus / agent-bus consumer")
st = gj("/agent-bus/status")
check(f"consumer running (handlers={st['handlers']})", st["running"] and st["enabled"])
# clean recent agent_bus invoice.overdue so the emitter fires fresh
sql("""DELETE FROM notifications WHERE event_uuid IN (SELECT event_uuid FROM events
       WHERE source_system='agent_bus' AND event_type IN ('invoice.overdue','invoice.dunning_drafted') AND created_at>now()-interval '1 day')""")
sql("""DELETE FROM event_queue WHERE event_uuid IN (SELECT event_uuid FROM events
       WHERE source_system='agent_bus' AND event_type IN ('invoice.overdue','invoice.dunning_drafted') AND created_at>now()-interval '1 day')""")
sql("DELETE FROM events WHERE source_system='agent_bus' AND event_type IN ('invoice.overdue','invoice.dunning_drafted') AND created_at>now()-interval '1 day'")
sql("DELETE FROM activities WHERE subject ILIKE 'Payment reminder%' AND created_at>now()-interval '1 day'")
n = sql("SELECT fn_emit_overdue_invoice_events(1)", fetch=True)[0][0]
tick = pj("/agent-bus/run-once")
drafts = sql("SELECT count(*) FROM activities WHERE subject ILIKE 'Payment reminder%' AND created_at>now()-interval '3 min'", fetch=True)[0][0]
acct = sql("""SELECT i.account_id FROM events e JOIN invoices i ON i.invoice_id=e.entity_uuid
             WHERE e.source_system='agent_bus' AND e.event_type='invoice.overdue' AND e.created_at>now()-interval '3 min' LIMIT 1""", fetch=True)
acct = str(acct[0][0]) if acct else None
check(f"emitted {n} + processed → {drafts} dunning draft(s)", n >= 0 and drafts >= 1)

# ── PHASE 2 — A2A protocol ─────────────────────────────────────────────────
print("PHASE 2 — A2A protocol")
caps = gj("/a2a/capabilities")
check(f"capability registry ({caps['count']} caps)", caps["count"] >= 20)
s = pj("/a2a/dispatch", {"intent": "leads.list", "params": {"scoreMin": 70, "pageSize": 5}})
recs = (s.get("data") or {}).get("records") or (s.get("data") or {}).get("leads") or []
check(f"structured dispatch leads.list scoreMin=70 → {len(recs)} recs ≥70",
      s["ok"] and recs and all((r.get("score") or 0) >= 70 for r in recs))
comp = pj("/a2a/dispatch", {"intent": "crm.pipeline_snapshot"})
check(f"peer handoff crm.pipeline_snapshot → hops={comp.get('hops')}", comp["ok"] and len(comp.get("hops") or []) == 2)
neg = pj("/a2a/dispatch", {"intent": "lead.list"})
check(f"negotiation lead.list → {(neg.get('data') or {}).get('suggestions')}", (not neg["ok"]) and "leads.list" in ((neg.get("data") or {}).get("suggestions") or []))
orch = pj("/orchestrator-chat", {"sessionId": "smoke", "chatInput": {"message": "list contacts please"}})
check(f"orchestrator capability routing (routedVia={orch.get('routedVia')})", orch.get("routedVia") == "a2a:contacts.query")

# ── PHASE 3 — proactive supervisor ─────────────────────────────────────────
print("PHASE 3 — Proactive supervisor")
sv = gj("/supervisor/status")
check(f"supervisor wired ({len(sv['detectors'])} detectors)", len(sv["detectors"]) == 4)
run = pj("/supervisor/run-once")
check(f"breach detection → {run.get('breaches')}", len(run.get("breaches") or []) >= 1 and "Briefing" in (run.get("briefing") or ""))

# ── PHASE 4 — shared blackboard ────────────────────────────────────────────
print("PHASE 4 — Shared blackboard")
if acct:
    ar = gj(f"/blackboard/account/{acct}")
    has_ar = any(nt["topic"] == "ar_risk" for nt in ar.get("notes", []))
    check(f"Phase-1 handler posted ar_risk to blackboard (note_count={ar['note_count']})", has_ar)
tid = str(uuid.uuid4())
pj("/blackboard", {"entity_type": "account", "entity_id": tid, "author_agent": "smoke",
                   "topic": "test", "note": "hello", "ttl_hours": 1})
ctx = gj(f"/blackboard/account/{tid}")
check("post + read note via API", ctx["note_count"] == 1 and "test" in ctx["topics"])
sql("DELETE FROM agent_blackboard WHERE entity_id=%s", (tid,))

# ── PHASE 5 — governance ───────────────────────────────────────────────────
print("PHASE 5 — Governance")
gs = gj("/governance/status")
check(f"governance wired (enabled={gs['enabled']}, act≥{gs['act_min']}, propose≥{gs['propose_min']})",
      "act_min" in gs and "propose_min" in gs)
check("approval queue endpoint", "pending" in gj("/governance/queue"))

# ── CLEANUP ────────────────────────────────────────────────────────────────
sql("""DELETE FROM notifications WHERE event_uuid IN (SELECT event_uuid FROM events
       WHERE source_system IN ('agent_bus','supervisor') AND created_at>now()-interval '15 min')""")
sql("""DELETE FROM event_queue WHERE event_uuid IN (SELECT event_uuid FROM events
       WHERE source_system IN ('agent_bus','supervisor') AND created_at>now()-interval '15 min')""")
sql("DELETE FROM events WHERE source_system IN ('agent_bus','supervisor') AND created_at>now()-interval '15 min'")
sql("DELETE FROM activities WHERE subject ILIKE 'Payment reminder%' AND created_at>now()-interval '15 min'")
sql("DELETE FROM agent_blackboard WHERE author_agent IN ('accounting','smoke') AND updated_at>now()-interval '15 min'")

print(f"\nSMOKE RESULT: {'ALL PASS ✅' if all(PASS) else 'FAIL ❌'}  ({sum(PASS)}/{len(PASS)} checks)")
