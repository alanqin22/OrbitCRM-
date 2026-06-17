# Agent Bus — Phase 1: Event-Driven Agent Cooperation

Turns the **latent** event bus already in the database into an **active** one: a
single consumer daemon that reacts to CRM events by dispatching the responsible
agent to *act* — and lets agents hand work to each other over the bus.

Pilot wired end-to-end: **overdue invoice → Accounting agent → Email agent.**

---

## What already existed (we built nothing here)

```
emit_event(type, entity, id, payload)
        │  INSERT
        ▼
     events ──────(AFTER INSERT trigger: trg_fn_events_after_insert)──────┐
        │                                                                  │
        ├─▶ event_queue            (status=pending, attempts, locked_by,   │
        │                           locked_at, next_attempt_at) ← work queue│
        │                                                                  │
        └─▶ notifications          fanned out per event_subscriptions,     │
            (channel='agent_inbox') one row per subscribing agent  ◀───────┘
```

- `event_types` — catalog; `emit_event` rejects unknown/inactive types.
- `event_subscriptions` — 102 rows mapping agent service accounts (employees
  `0…01`–`0…12`) → event types they care about.
- **The gap:** nobody consumed `event_queue` — 19,887 rows sat `pending` forever.

## What Phase 1 adds

| Piece | File | Role |
|---|---|---|
| Consumer daemon + handler registry | `app/core/agent_bus.py` | claims queue rows, routes by `event_type` to a Python handler, completes / retries |
| Pilot #1 `invoice.overdue` | same file | Accounting agent: draft reminder, log activity, hand off to Email |
| Pilot #2 `lead.scored` (≥70) | same file | Lead→Activity: auto-schedule outreach call, hand off to Notifications |
| DB wiring | `sql/agent_bus_pilot.sql` | registers new event types, subscribes the agents, adds `fn_emit_overdue_invoice_events()` + `fn_emit_hot_lead_events()` |
| Lifespan hook + admin routes | `app/main.py` | starts/stops the daemon; `GET /agent-bus/status`, `POST /agent-bus/run-once` |
| End-to-end tests | `scratch/test_agent_bus_pilot.py`, `scratch/test_agent_bus_lead.py` | prove both loops, idempotent & repeatable |

## The pilot flow

```
fn_emit_overdue_invoice_events()                 [or any future trigger]
   └─ emit_event('invoice.overdue', invoice) ──▶ events ─▶ event_queue (pending)
                                                        └▶ AccountingAgent inbox
   ┌───────────────────────────────────────────────────────────────────────┐
   │  agent_bus consumer tick                                               │
   │   1. claim pending invoice.overdue rows  (FOR UPDATE SKIP LOCKED)      │
   │   2. handle_invoice_overdue():                                         │
   │        • re-check materiality (paid since emit? → skip)                │
   │        • idempotency: already dunned in 20h? → skip                    │
   │        • compose tiered reminder (gentle / firm / urgent)              │
   │        • log Activity on the invoice  (Accounting's action record)     │
   │        • emit_event('invoice.dunning_drafted')  ──▶ EmailAgent inbox   │ ← A2A handoff
   │        • if AGENT_BUS_AUTOSEND=1 → _call_agent('/email-chat', …) SMTP  │
   │   3. mark queue row completed + settle agent_inbox notifications       │
   └───────────────────────────────────────────────────────────────────────┘
```

The handoff is itself a bus event, so it's durable, audited, and fans out to any
agent subscribed to `invoice.dunning_drafted` (today: Email).

## Safety / governance (why this is enterprise-safe)

- **Opt-in:** dormant unless `AGENT_BUS_ENABLED=1`.
- **Tiny blast radius:** only event types with a registered handler are ever
  touched. The 1,554 legacy `invoice_overdue` (underscore) rows are ignored — the
  pilot uses the canonical dotted `invoice.overdue` (≈0 backlog).
- **No mass replay:** boot cutoff means only events from start-up forward are
  processed (`AGENT_BUS_BACKFILL_MINUTES` to reach back deliberately).
- **At-least-once + retry:** row-level lock with 5-min stale-lock reclaim;
  exponential backoff; `status='failed'` after `AGENT_BUS_MAX_ATTEMPTS`.
- **Idempotent:** emitter guards one `invoice.overdue` per invoice / 20h; handler
  skips if a reminder already exists or the invoice is no longer materially overdue.
- **No outbound by default:** drafts + logs + hands off. Real SMTP only when
  `AGENT_BUS_AUTOSEND=1`. Atomic — if the handoff emit fails, the activity insert
  rolls back with it (verified).

## Config (env)

| Var | Default | Meaning |
|---|---|---|
| `AGENT_BUS_ENABLED` | `0` | master switch |
| `AGENT_BUS_POLL_SECS` | `30` | seconds between ticks |
| `AGENT_BUS_BATCH` | `10` | max events per tick |
| `AGENT_BUS_MAX_ATTEMPTS` | `5` | retries before `failed` |
| `AGENT_BUS_AUTOSEND` | `0` | `1` = actually send via Email agent |
| `AGENT_BUS_BACKFILL_MINUTES` | `0` | also process recent pre-boot events |

## Run it

```bash
# 1. one-time DB wiring (local)
psql "$DB_DSN" -f sql/agent_bus_pilot.sql

# 2a. automated proof (no server needed; draft mode)
python scratch/test_agent_bus_pilot.py          # → RESULT: PASS ✅

# 2b. or live, via the running server
#   set AGENT_BUS_ENABLED=1 in .env, then:
python main.py
#   emit + drive a tick on demand:
psql "$DB_DSN" -c "SELECT fn_emit_overdue_invoice_events(5);"
curl -X POST localhost:8000/agent-bus/run-once
curl localhost:8000/agent-bus/status
```

### Automatic nightly sweeps

The two emitters are wired into the existing APScheduler (10 PM US Eastern,
DST-aware), staggered after the seed jobs:

| Time (ET) | Job | Emits |
|---|---|---|
| 22:25 | `emit_overdue_invoice_events` | `invoice.overdue` → Accounting → Email |
| 22:30 | `emit_hot_lead_events` | `lead.scored` (Hot) → Activity → Notifications |

Both **self-gate on `AGENT_BUS_ENABLED`** — if the bus is off they log "skipped"
and emit nothing (so events never queue without a consumer). With the bus on, the
consumer (same process) picks the new events up on its next poll. So once
`AGENT_BUS_ENABLED=1`, the whole loop runs hands-off every night.

Railway: apply `sql/agent_bus_pilot.sql` there too and set the env vars. The
APScheduler runs inside the FastAPI process; alternatively a `pg_cron` job can
call the two `fn_emit_*` functions on the Railway database directly.

## Pilot #2 — the pattern generalizing

`lead.scored` (Hot, score ≥ 70) → **Lead → Activity → Notifications**, on the
exact same consumer, queue, retry, and governance — proving the cooperation
pattern is reusable, not bespoke:

```
fn_emit_hot_lead_events()  [prod: the lead-scoring SP emits lead.scored on rescore]
   └─ emit_event('lead.scored', lead) ──▶ events ─▶ queue ─▶ Lead/Activity/Notif inboxes
   ┌──────────────────────────────────────────────────────────────────────┐
   │  handle_lead_scored():                                                │
   │    • re-check Hot (≥70), open, not converted/disqualified → else skip │
   │    • idempotency: outreach already scheduled in 3 days? → skip        │
   │    • create outreach Activity (call, due in 4h)  ← Activity agent      │
   │    • emit_event('lead.outreach_scheduled') ──▶ Notifications inbox     │ ← handoff
   └──────────────────────────────────────────────────────────────────────┘
```

Adding the second cooperation was purely additive: **one handler** +
**three subscription rows** + **two event types** + **one emitter** — no change
to the consumer core. The recipe for any future cooperation:
**register a handler** + **subscribe agents** + **(optionally) register an event type**.

## Known quirk (pre-existing, handled)

`emit_event()` and the events AFTER-INSERT trigger *both* enqueue, so each event
gets two `event_queue` rows (the trigger's de-dup guard misses `emit_event` due
to in-transaction visibility). The consumer is robust to this: it **keys claimed
rows by `event_uuid`** (deduping) and `complete`/`fail` act by `event_uuid`
(settling every row), so each event is handled exactly once per tick. Fixing the
double-enqueue at the source (a `UNIQUE(event_uuid)` on `event_queue`, or having
`emit_event` not self-enqueue) is a worthwhile but separate bus-hygiene change.

## Related fix — overdue events self-resolve on settlement

`invoice_overdue` events fanned out queue rows + notifications when an invoice went
overdue, but nothing closed them when the invoice was later **paid** — so the
backlog filled with phantom "overdue" alerts for settled invoices (~96% of pending
`invoice_overdue` rows were already paid: local 1,554→72, Railway 946). Fixed in
`trgfn_invoice_after.sql` §4: on transition to `paid`/`cancelled` it resolves the
pending `invoice_overdue` / `invoice.overdue` queue rows (`→ superseded`) and
notifications (`→ read`) for that invoice. One-time backlog cleanup:
`sql/resolve_stale_overdue_events.sql`. Both apply to Railway the same way. After
this, a long `invoice_overdue` pending backlog is a red flag, not normal.

## How this generalizes further (Phase 2+)

`opportunity.slipped → Opportunity asks Analytics for risk → drafts save-play via Email`,
`payment.failed → Accounting + Notifications + Email`, etc. The typed A2A envelope,
capability registry, and shared blackboard from the broader plan slot in on top
of this same consumer.
