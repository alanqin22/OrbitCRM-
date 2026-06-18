# Agent Bus — Phase 2: Typed Agent-to-Agent (A2A) Protocol

First increment of Phase 2. Upgrades cross-agent calls from ad-hoc plain-English
`_call_agent(path, string)` to a **typed, discoverable, capability-routed** layer.

## Why

Phase 1 agents cooperate two ways: durable async **event handoffs** (emit a
follow-up event → fan-out to a peer's inbox) and the orchestrator's synchronous
`_call_agent(endpoint, english_string)`. The latter is brittle: a hardcoded
endpoint + a screen-scraped `output`, routed by keyword (`_route_single`). Phase 2
makes the synchronous path a real protocol.

## What Phase 2 adds (`app/core/a2a.py`)

- **Typed envelope** — `A2ARequest(intent, from_agent, entity, params,
  correlation_id, confidence, requires_ack)` and `A2AResult(ok, agent, data,
  output, error, correlation_id)`. A call is a structured contract, not a string.
- **Capability registry** — `CAPABILITIES: intent → Capability(agent, endpoint,
  kind, render, description)`, seeded from each agent's `VALID_MODES`. Callers
  route by **capability** (what they want done), not by endpoint.
- **`dispatch(req, dry_run=False)`** — resolves the intent's capability, renders
  the agent's message, invokes the owning agent **in-process** (httpx ASGI, no
  network hop), and returns a structured `A2AResult` with correlation lineage.
  `kind` declares read vs write; `dry_run` resolves + routes with no side effect.
- **Discovery / ad-hoc call** — `GET /a2a/capabilities` (manifest),
  `POST /a2a/dispatch`.

Additive and safe: each agent's input contract is unchanged (still
`{chatInput:{message}}`), and the messages used are ones the orchestrator already
routes (e.g. `accounting summary`, `list leads:`), so routing stays deterministic.

## Registered capabilities (first cut)

| intent | agent | kind | structured |
|---|---|---|---|
| `accounting.summary` | accounting | read | ✓ |
| `leads.list` | leads | read | ✓ |
| `orders.sales_summary` | orders | read | ✓ |
| `activities.list` | activities | read | ✓ |
| `contacts.list` | contacts | read | ✓ |
| `opportunities.pipeline` | opportunities | read | ✓ |
| `products.low_stock` | products | read | ✓ |
| `accounting.account_balance` | accounting | read | |
| `email.send_payment_reminder` | email | write | |
| `crm.pipeline_snapshot` | orchestrator | read | composite |
| `<agent>.query` (×11) | each agent | read | NL passthrough |

"structured" = direct-SP path returning data; "composite" = delegates to peers;
`<agent>.query` = forwards a natural-language message to that agent (used by the
orchestrator's single-agent routing). **21 capabilities** total.

## In use

The agent-bus `invoice.overdue` handler's Email handoff (AUTOSEND path) now
dispatches a typed request instead of a hardcoded `_call_agent`:

```python
res = await dispatch(A2ARequest(
    from_agent="accounting", intent="email.send_payment_reminder",
    entity=EntityRef("invoice", invoice_id),
    params={"to": ..., "invoice_number": ..., "amount": ..., "days_overdue": ...},
    correlation_id=..., confidence=0.9))
```

## Structured input contract (non-NL)

A capability may declare a `sp` handler — `params → structured data` via the
owning agent's SQL builder + SP, with **no NL parsing, no AI, no HTTP**. When
present, `dispatch()` uses it by default (agent-to-agent wants *data*, not prose):

```python
# typed params, deterministic — not "show leads scoring above 70"
res = await dispatch(A2ARequest(intent="leads.list", params={"scoreMin": 70}))
res.data    # → {records: [...]}  (structured)
```

Pass `prose=True` to force the NL/agent path (formatted markdown) instead.
Today `accounting.summary` and `leads.list` have structured paths.

## Orchestrator capability routing

The orchestrator can route by **capability** via the registry, not just keyword
`_route_single` (additive — only these explicit handles trigger it):

- `capabilities` → the capability manifest (intent · agent · kind · structured).
- `route: <intent> [k=v ...]` → resolve + dispatch to the owning agent, returning
  the structured result. e.g. `route: leads.list scoreMin=70`.

Governance: a **write** capability dry-runs by default; add `confirm` to execute.

**Single-agent delegation is now A2A-routed** (the primary path): `_route_single`
still selects the agent, but the call goes through `dispatch(<agent>.query, prose)`
— typed, correlated (`correlation_id = session`), registry-driven — falling back
to a direct `_call_agent` only if no passthrough capability is registered. The
agent's full response is preserved (`A2AResult.raw`) and tagged `routedVia`.

## Peer handoff / negotiation

A capability can be **composite**: its handler delegates sub-intents to peer
agents via `delegate(parent, sub_intent, params)` and composes their structured
results. The parent's `correlation_id` propagates to every hop, and the result
carries a `hops` audit trail.

```python
# crm.pipeline_snapshot fans out to Accounting + Leads and composes:
res = await dispatch(A2ARequest(intent="crm.pipeline_snapshot"))
res.data    # {financials, hot_leads, top_hot}
res.hops    # ["accounting.summary", "leads.list"]
```

**Negotiation:** an unknown intent doesn't just fail — `dispatch` returns the
closest registered intents as `suggestions` (e.g. `lead.list` → `leads.list`),
so the caller can recover.

## Add a capability

Append one line to `CAPABILITIES`:

```python
Capability("<intent>", "<agent>", "/<agent>-chat", "read|write",
           lambda p: "<message the target agent routes>", "<description>")
```

`render(params)` should produce a message the target agent routes
deterministically (a known prefix beats free text).

## Test

`python scratch/test_a2a.py` → **PASS** — manifest, intent→agent resolution +
`to_agent` pinning, dry-run (no side effect), real in-process read dispatches
(`accounting.summary`, `leads.list`), and correlation lineage.

## Next (rest of Phase 2 / done)

Phase 2 is essentially complete: typed envelope, capability registry (21 caps),
structured contract, peer handoff + negotiation, and capability routing as the
orchestrator's primary single-agent path. Remaining polish: even wider structured
coverage and more composite plays; confidence-gating + approval queue fold into
Phase 5.
- Make capability routing the orchestrator's *primary* single-agent path (today
  it's an additive `route:` handle; `_route_single` still handles free-form NL).
- Confidence-gating + an approval queue for write capabilities (ties to Phase 5).
