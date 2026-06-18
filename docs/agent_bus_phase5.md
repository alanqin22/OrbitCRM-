# Agent Bus — Phase 5: Governance (confidence-gating + approval queue)

The layer that makes the autonomy **safe to turn on**. Every WRITE/outbound A2A
action is gated by its confidence; medium-confidence actions queue for a human;
every proposal and decision is audited.

## The gate

```
A2ARequest.confidence ─▶ governance.decide()
    >= GOV_ACT_MIN (0.8)        → ACT      execute now
    GOV_PROPOSE_MIN..ACT_MIN    → PROPOSE  queue in action_approvals (pending)
    < GOV_PROPOSE_MIN (0.5)     → SKIP     don't act
```

- Only **write** capabilities are gated; reads always execute.
- No-op unless `GOV_ENABLED=1` — otherwise writes execute exactly as before
  (additive, opt-in).
- Wired into `a2a.dispatch`: a gated write returns `{status: pending_approval,
  approval_uuid}` (proposed) or an error (skipped) **without invoking** the agent.

## The approval queue (`action_approvals`, `sql/governance.sql`)

A proposed action is a row: `action_type` (the A2A intent), `proposed_by`,
`entity`, `params`, `confidence`, `severity`, `status`
(`pending→approved→executed|failed` / `rejected`), `decided_by/at/reason`,
`result`. A human:

- **Approves** → the action is **re-dispatched through A2A with the gate bypassed**
  (`govern_bypass=True`), and the result recorded (`executed`/`failed`).
- **Rejects** → `rejected`, never runs.

## API (`app/core/governance.py`)

```python
decide(confidence) -> 'act'|'propose'|'skip'
propose(action_type, proposed_by, params, entity_type=, entity_id=, confidence=, …)
pending(); reject(id, decided_by, reason)
await approve(id, decided_by, reason)        # → executes via A2A, records result
```

Endpoints: `GET /governance/status`, `GET /governance/queue`,
`POST /governance/approve/{id}`, `POST /governance/reject/{id}`.

## Config (env)

| var | default | meaning |
|---|---|---|
| `GOV_ENABLED` | `0` | master on/off (gating no-ops when 0) |
| `GOV_ACT_MIN` | `0.8` | confidence at/above which a write auto-executes |
| `GOV_PROPOSE_MIN` | `0.5` | confidence at/above which a write is queued (else skip) |

## Why it completes the picture

The `confidence` field has been on every `A2ARequest` since Phase 2; the
agent-bus Email handoff dispatches with `confidence=0.9`. With `GOV_ENABLED=1`,
turning on `AUTOSEND` is no longer all-or-nothing: high-confidence dunning sends,
medium-confidence queues for a human, low-confidence is skipped — all audited.
This is what lets the loop run in production safely.

## Test

`python scratch/test_governance.py` → **PASS ✅** — policy (act/propose/skip),
a medium-confidence write proposes (not sent), low-confidence skips, the queue
shows it, reject works, and approve→execute re-dispatches with the gate bypassed
(stubbed so nothing is actually sent). Live smoke-tested.

## Run

```bash
psql "$DB_DSN" -f sql/governance.sql
# enable in .env: GOV_ENABLED=1, then:
curl localhost:8000/governance/queue
curl -X POST localhost:8000/governance/approve/<uuid>
```

## Next

- Gate the supervisor's `AUTOACT` through the same queue (medium-confidence
  breaches propose instead of auto-firing).
- Confidence from the blackboard / detectors feeding the gate.
- Reversibility (undo) + expiry sweep for stale pending approvals.
