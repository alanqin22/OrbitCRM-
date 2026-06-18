"""Phase 2 — Agent-to-Agent (A2A) protocol.

Upgrades cross-agent calls from ad-hoc plain-English `_call_agent(path, string)`
to a typed, discoverable, capability-routed layer:

  • A typed ENVELOPE (A2ARequest / A2AResult) carrying intent, entity ref,
    params, correlation_id, and confidence — so a call is a structured contract,
    not a screen-scrape.
  • A capability REGISTRY (intent → which agent owns it, built on each agent's
    modes) — callers route by *capability*, not a hardcoded endpoint or the
    orchestrator's keyword `_route_single`.
  • dispatch() — resolves the capability, invokes the owning agent IN-PROCESS
    (httpx ASGI, no network hop), and returns a structured A2AResult with
    correlation lineage. Read vs write is declared per capability.

This is ADDITIVE and safe: each agent's input contract is unchanged (it still
receives `{chatInput:{message}}`), so the agents' existing deterministic/NL
routing is reused — A2A just wraps the call in a typed, governable envelope.
The messages used here are the same ones the orchestrator already calls agents
with (e.g. 'accounting summary', 'list leads:'), so routing is deterministic.
"""

from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger("a2a")


# ============================================================================
# ENVELOPE
# ============================================================================

@dataclass
class EntityRef:
    type: str
    id: str


@dataclass
class A2ARequest:
    """A typed agent-to-agent request."""
    intent: str
    from_agent: str = "system"
    entity: Optional[EntityRef] = None
    params: Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None
    confidence: float = 1.0          # caller's confidence in the request (0–1)
    requires_ack: bool = False
    prose: bool = False              # True = force the NL/agent path (formatted
                                     # output); default uses the structured SP
                                     # path when the capability declares one.


@dataclass
class A2AResult:
    ok: bool
    intent: str
    agent: str
    correlation_id: str
    data: Any = None
    output: str = ""
    error: Optional[str] = None


# ============================================================================
# CAPABILITY REGISTRY  (intent → owning agent)
# ============================================================================

@dataclass
class Capability:
    intent: str
    agent: str
    endpoint: str
    kind: str                             # 'read' | 'write'
    render: Callable[[Dict[str, Any]], str]   # params → the agent's NL message
    description: str
    # Optional STRUCTURED input contract: params → structured data, via the
    # owning agent's SQL builder + SP (no NL parsing, no AI, no HTTP). When set,
    # dispatch() prefers this for deterministic agent-to-agent data exchange.
    sp: Optional[Callable[[Dict[str, Any]], Any]] = None


def _reg(*caps: Capability) -> Dict[str, Capability]:
    return {c.intent: c for c in caps}


# ---- structured (direct-SP) capability handlers ----------------------------
def _sp_exec(build: Callable, params: Dict[str, Any]) -> Any:
    """Build an SP call via an agent's sql_builder and return its structured
    result (unwrapping the {'result': ...} row when present)."""
    from app.core.database import execute_sp
    sql, _ = build(params)
    rows = execute_sp(sql)
    if rows and isinstance(rows[0], dict) and "result" in rows[0]:
        return rows[0]["result"]
    return rows


def _sp_accounting_summary(p: Dict[str, Any]) -> Any:
    from app.agents.accounting.sql_builder import build_accounting_query
    return _sp_exec(build_accounting_query, {"mode": "accounting_summary"})


def _sp_leads_list(p: Dict[str, Any]) -> Any:
    from app.agents.leads.sql_builder import build_leads_query
    q: Dict[str, Any] = {"mode": "list", "pageSize": p.get("pageSize", 20)}
    for k in ("scoreMin", "scoreMax", "status", "rating"):
        if p.get(k) is not None:
            q[k] = p[k]
    return _sp_exec(build_leads_query, q)


# Seeded from the agents' own VALID_MODES; messages are deterministic prefixes
# / phrasings each target agent already routes (proven by the orchestrator).
CAPABILITIES: Dict[str, Capability] = _reg(
    Capability("accounting.summary", "accounting", "/accounting-chat", "read",
               lambda p: "accounting summary",
               "AR/AP financial health summary",
               sp=_sp_accounting_summary),
    Capability("accounting.account_balance", "accounting", "/accounting-chat", "read",
               lambda p: f"account balance: {p.get('account', '')}",
               "outstanding / paid / overdue balance for an account"),
    Capability("leads.list", "leads", "/lead-chat", "read",
               lambda p: "list leads:",
               "list leads (structured params: scoreMin/scoreMax/status/rating)",
               sp=_sp_leads_list),
    Capability("orders.sales_summary", "orders", "/order-chat", "read",
               lambda p: "Sales summary this month",
               "monthly sales summary"),
    Capability("activities.list", "activities", "/activity-chat", "read",
               lambda p: "list activities:",
               "list activities"),
    Capability("email.send_payment_reminder", "email", "/email-chat", "write",
               lambda p: (f"send a payment reminder email to {p['to']} about invoice "
                          f"{p.get('invoice_number', '')} for {p.get('amount', '')}, "
                          f"{p.get('days_overdue', '')} days overdue"),
               "send an overdue-invoice payment reminder"),
)


def resolve(intent: str, to_agent: Optional[str] = None) -> Optional[Capability]:
    """Route by capability. If to_agent is given it must match (lets a caller
    pin a specific agent when several could serve an intent)."""
    cap = CAPABILITIES.get(intent)
    if cap and to_agent and cap.agent != to_agent:
        return None
    return cap


def manifest() -> Dict[str, Any]:
    """Discoverable capability manifest (what each agent can be asked to do)."""
    by_agent: Dict[str, List[str]] = {}
    caps = []
    for c in CAPABILITIES.values():
        caps.append({"intent": c.intent, "agent": c.agent, "endpoint": c.endpoint,
                     "kind": c.kind, "structured": c.sp is not None,
                     "description": c.description})
        by_agent.setdefault(c.agent, []).append(c.intent)
    return {"count": len(caps), "capabilities": caps, "by_agent": by_agent}


# ============================================================================
# IN-PROCESS INVOKE (ASGI — no network hop)
# ============================================================================

async def _invoke(endpoint: str, message: str, session_id: str) -> dict:
    from app.main import app as _app  # lazy import avoids a circular import
    transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://a2a.internal",
                                 timeout=300) as client:
        resp = await client.post(endpoint, json={
            "sessionId": session_id,
            "chatInput": {"message": message},
        })
        try:
            data = resp.json()
        except Exception:
            return {"output": resp.text[:2000]}
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {"output": str(data)[:2000]}


# ============================================================================
# DISPATCH
# ============================================================================

def _summarize(intent: str, data: Any) -> str:
    if isinstance(data, dict):
        recs = data.get("records") or data.get("leads") or data.get("data")
        if isinstance(recs, list):
            return f"{intent}: {len(recs)} record(s)"
        return f"{intent}: {len(data)} field(s)"
    if isinstance(data, list):
        return f"{intent}: {len(data)} row(s)"
    return f"{intent}: ok"


async def dispatch(req: A2ARequest, dry_run: bool = False) -> A2AResult:
    """Resolve the intent's capability and invoke the owning agent in-process."""
    cid = req.correlation_id or str(_uuid.uuid4())
    cap = resolve(req.intent, getattr(req, "to_agent", None))
    if not cap:
        return A2AResult(False, req.intent, "none", cid,
                         error=f"No capability registered for intent '{req.intent}'")

    structured = cap.sp is not None and not req.prose
    if dry_run:
        via = "structured SP (data)" if structured else f"agent {cap.endpoint} (prose)"
        return A2AResult(True, req.intent, cap.agent, cid,
                         output=f"[dry-run] would route '{req.intent}' → "
                                f"{cap.agent} via {via}")

    # Structured input contract: deterministic params → SP → structured data.
    # No NL parsing, no AI, no HTTP — the default for agent-to-agent calls.
    if structured:
        try:
            data = await asyncio.to_thread(cap.sp, req.params)
        except Exception as exc:
            return A2AResult(False, req.intent, cap.agent, cid,
                             error=f"sp failed for '{req.intent}': {exc}")
        logger.info(f"[a2a] {req.from_agent} → {cap.agent}.{req.intent} "
                    f"(structured) cid={cid[:8]}")
        return A2AResult(True, req.intent, cap.agent, cid, data=data,
                         output=_summarize(req.intent, data))

    try:
        message = cap.render(req.params)
    except Exception as exc:
        return A2AResult(False, req.intent, cap.agent, cid,
                         error=f"render failed for '{req.intent}': {exc}")

    session = f"a2a-{req.from_agent}-{cid[:8]}"
    logger.info(f"[a2a] {req.from_agent} → {cap.agent}.{req.intent} "
                f"(conf={req.confidence}) cid={cid[:8]}")
    resp = await _invoke(cap.endpoint, message, session)
    return A2AResult(
        ok=(resp.get("success") is not False) and not resp.get("error"),
        intent=req.intent, agent=cap.agent, correlation_id=cid,
        data=resp.get("records") if "records" in resp else resp.get("result"),
        output=str(resp.get("output", ""))[:4000],
        error=resp.get("error"),
    )


# ============================================================================
# DISCOVERY + DISPATCH ENDPOINTS
# ============================================================================

router = APIRouter(tags=["a2a"])


@router.get("/a2a/capabilities")
def a2a_capabilities():
    return manifest()


class _DispatchBody(BaseModel):
    intent: str
    from_agent: str = "system"
    params: Dict[str, Any] = {}
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    correlation_id: Optional[str] = None
    confidence: float = 1.0
    prose: bool = False
    dry_run: bool = False


@router.post("/a2a/dispatch")
async def a2a_dispatch(body: _DispatchBody):
    req = A2ARequest(
        intent=body.intent, from_agent=body.from_agent, params=body.params,
        entity=EntityRef(body.entity_type, body.entity_id) if body.entity_type else None,
        correlation_id=body.correlation_id, confidence=body.confidence,
        prose=body.prose,
    )
    return asdict(await dispatch(req, dry_run=body.dry_run))
