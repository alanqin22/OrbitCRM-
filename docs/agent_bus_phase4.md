# Agent Bus — Phase 4: Shared Agent Memory ("Blackboard")

The leap from agents that **call** each other to agents that **understand the
same situation**. An entity-keyed store where any agent posts a structured
observation and any other agent reads it — so they coordinate through shared
context, not just direct calls.

## The store (`agent_blackboard`, `sql/blackboard.sql`)

| column | meaning |
|---|---|
| `entity_type`, `entity_id` | what the note is about (account / lead / invoice / …) |
| `author_agent`, `topic` | who said it, about what (`ar_risk`, `champion`, `dunning_hold`, …) |
| `note`, `value` (jsonb) | the human note + structured payload |
| `confidence`, `severity` | how sure, how serious |
| `expires_at` | optional TTL — stale context ages out |

One note per `(entity, author, topic)` — re-posting **upserts** (each agent keeps
one current note per topic per entity).

## API (`app/core/blackboard.py`)

```python
post(entity_type, entity_id, author_agent, topic, note, value=, confidence=,
     severity=, ttl_hours=)        # upsert an observation
read(entity_type, entity_id, topic=None)   # current (non-expired) notes
context(entity_type, entity_id)            # all notes + topic→authors index
clear(entity_type, entity_id, author=, topic=)
```

Endpoints: `GET /blackboard/{entity_type}/{entity_id}` · `POST /blackboard`.
A2A: `account.context` capability returns an account's shared context.

## In use — agents coordinating through context

- **Sales posts a hold → Accounting backs off.** The overdue-invoice handler
  reads the account's blackboard before dunning; if another agent posted a
  `dunning_hold` (e.g. "in contract renewal — hold 7 days"), it **skips**. Agents
  coordinate without calling each other.
- **Accounting posts AR risk.** When it does dun, it posts an `ar_risk` note on
  the account, so Sales / the supervisor / an account 360 see it without asking.
- **Leads post hot-lead context.** The lead handler posts a `hot_lead` note.

## Safe & additive

Reads are advisory (a missing/empty blackboard changes nothing); the hold check
only suppresses when a hold note actually exists. TTL keeps it self-cleaning. No
change to existing behavior; separate table, no event-bus coupling.

## Test

`python scratch/test_blackboard.py` → **PASS ✅** — post/read/context, upsert,
TTL, and the cross-agent scenario (hold suppresses dunning; `ar_risk` posted;
`account.context` reads it back). Live smoke-tested via the endpoints.

## Run

```bash
psql "$DB_DSN" -f sql/blackboard.sql
curl localhost:8000/blackboard/account/<uuid>
```

Apply `sql/blackboard.sql` on Railway to go live there (no env flags needed).

## Next

- More posters/readers (opportunities post `negotiation`, activities post
  `last_touch`, the supervisor posts breach context per entity).
- Surface the blackboard in account/contact 360 views and the exec briefing.
- Confidence-weighted conflict resolution when two agents disagree (→ Phase 5).
