# Agent Bus — Phase 3: Proactive Supervisor

Promotes the orchestrator from **request-scoped** to a **standing loop**: a
scheduled tick reads the live KPI pack, detects breaches, and acts — so the
system flags (and optionally fixes) problems **without being asked**. This is the
"agents act unprompted" differentiator, built on Phases 1–2.

## The loop (`app/core/supervisor.py`)

```
every 3 hours (business hrs)        sense        decide         act          record
   _run_supervisor_tick()  ─▶  sp_orchestrator   detectors  ─▶  emit         events +
                               ('executive')     (rules)        supervisor.   agent_inbox
                                                                alert          fan-out
                                                                  │
                                                  (SUPERVISOR_AUTOACT) ─▶ kick owning
                                                  agent's loop (e.g. AR → dunning)
```

- **Sense** — `sp_orchestrator('executive')` (the same pack the exec Q&A uses).
- **Decide** — detectors map KPIs → breach signals (headline, severity, owner
  agent, recommended action):

  | rule | trips when | owner | recommended action |
  |---|---|---|---|
  | `ar_spike` | `overdue_count ≥ 10` | accounting | run overdue dunning |
  | `slipped_deals` | `forecast.slipped_count ≥ 10` | opportunities | re-engage / re-date |
  | `unbilled_orders` | `unbilled_orders.count ≥ 3` | accounting | invoice shipped orders |
  | `unworked_leads` | `unworked_leads.count ≥ 25` | leads | score + auto-outreach |

- **Act** — emit a `supervisor.alert` event (auditable; fans out to the
  Notifications + Orchestrator agent inboxes). With `SUPERVISOR_AUTOACT=1` it also
  kicks the owning agent's loop (AR → `fn_emit_overdue_invoice_events`, unworked
  leads → `fn_emit_hot_lead_events`), reusing the Phase 1 emitters.
- **Record** — every alert is an event row (audit), idempotent: one alert per
  rule per 12 h.

## Output — a proactive briefing

```
### 🛰️ Supervisor Briefing — 4 issue(s) need attention
- 🟠 14 invoices overdue · $2,188 outstanding   → Run overdue dunning (owner: accounting)
- 🟠 19 deals slipped past close date · $457,374 at risk → Re-engage (owner: opportunities)
- 🟠 5 shipped orders unbilled · $7,191 revenue leakage  → Generate invoices (owner: accounting)
- 🟠 57 leads unworked — coverage at risk        → Score + outreach (owner: leads)
```

## Safe by default

- **Gated**: dormant unless `SUPERVISOR_ENABLED=1`; the scheduled tick is a no-op
  otherwise (admin `run-once` can `force`).
- **Alert-only by default**: no agent loops kicked unless `SUPERVISOR_AUTOACT=1`.
- **Idempotent**: one alert per rule per 12 h (checked against the event log).
- **Auditable**: every action is a `supervisor.alert` event with the signal under
  the canonical payload `context`.

## Config (env)

| var | default | meaning |
|---|---|---|
| `SUPERVISOR_ENABLED` | `0` | master on/off (scheduled tick no-ops when 0) |
| `SUPERVISOR_AUTOACT` | `0` | `1` = also kick owning-agent loops on breach |
| `SUPERVISOR_AR_OVERDUE_MIN` | `10` | overdue-invoice count → AR alert |
| `SUPERVISOR_SLIPPED_MIN` | `10` | slipped-deal count → forecast alert |
| `SUPERVISOR_UNBILLED_MIN` | `3` | unbilled-order count → leakage alert |
| `SUPERVISOR_UNWORKED_MIN` | `25` | unworked-lead count → coverage alert |

## Run / test

```bash
psql "$DB_DSN" -f sql/supervisor.sql          # register event type + subscriptions
python scratch/test_supervisor.py             # → RESULT: PASS ✅
# live:
curl localhost:8000/supervisor/status
curl -X POST localhost:8000/supervisor/run-once     # detects + alerts (idempotent)
```

Scheduled: `_run_supervisor_tick` runs **every 3 hours — 9/12/15/18 ET, Mon–Fri**
(alongside the nightly jobs). Apply `sql/supervisor.sql` on Railway and set the
env vars to go live there.

## Next (rest of Phase 3)

- Richer detectors (revenue dip vs prior month, churn-risk, discount spikes — the
  KPI pack already carries them).
- Per-breach A2A dispatch that attaches drill-down context to the alert.
- Confidence-gating + approval queue for `AUTOACT` writes (→ Phase 5).
