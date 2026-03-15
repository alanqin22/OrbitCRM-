# CRM Agent

Unified CRM AI Agent — all domain agents (accounts, contacts, and 8 future
modules) running on a single FastAPI + LangGraph server.

---

## Project Structure

```
crm_agent/
├── main.py                        ← Top-level entry point
├── requirements.txt
├── .env                           ← Single config file for all agents
└── app/
    ├── main.py                    ← FastAPI app — registers all routers
    ├── core/                      ← Shared utilities (zero duplication)
    │   ├── config.py              ← Unified Settings (pydantic-settings)
    │   ├── database.py            ← Generic execute_sp() + test_connection()
    │   ├── memory.py              ← Shared session memory (rolling window)
    │   └── graph_utils.py         ← AgentState, LLM factory, JSON parser,
    │                                 build_standard_graph()
    └── agents/
        ├── accounts/              ← Accounts domain
        │   ├── prompt.py          ← ACCOUNT_AGENT_SYSTEM_PROMPT
        │   ├── pre_router.py      ← Deterministic routing (v3.0)
        │   ├── sql_builder.py     ← build_accounts_query()
        │   ├── formatter.py       ← format_response() for sp_accounts
        │   ├── graph.py           ← LangGraph nodes + get_graph()
        │   └── router.py          ← FastAPI routes (/account-chat)
        ├── contacts/              ← Contacts domain
        │   ├── prompt.py          ← CONTACT_AGENT_SYSTEM_PROMPT
        │   ├── pre_router.py      ← Deterministic routing (v3.1)
        │   ├── sql_builder.py     ← build_contacts_query()
        │   ├── formatter.py       ← format_response() for sp_contacts
        │   ├── graph.py           ← LangGraph nodes + get_graph()
        │   └── router.py          ← FastAPI routes (/contact-chat)
        └── <future_agent>/        ← Drop in 8 more agents here
```

---

## Quick Start

```bash

python -m venv venv

.\venv\Scripts\activate

# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env .env.local   # then edit .env with your DB_DSN, LLM settings
# OR just edit .env directly

# 3. Run
python main.py
# or
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API Endpoints

| Method | Path              | Description                        |
|--------|-------------------|------------------------------------|
| GET    | /                 | Service info                       |
| GET    | /health           | Aggregate health check             |
| POST   | /account-chat     | Accounts agent (drop-in for 8003)  |
| GET    | /account-health   | Accounts agent health              |
| POST   | /contact-chat     | Contacts agent (drop-in for 8004)  |
| GET    | /contact-health   | Contacts agent health              |
| GET    | /sessions         | List active memory sessions        |
| DELETE | /sessions/{id}    | Clear a session's memory           |

### Backward Compatibility
Existing HTML frontends only need the **port number updated** from
`8003` / `8004` → `8000`.  The endpoint paths (`/account-chat`,
`/contact-chat`) and request/response shapes are identical.

---

## Architecture

Every agent follows the same deterministic-first pattern:

```
Request
  └─► FastAPI router.py
        └─► graph.py
              └─► pre_router_node
                    ├─[ROUTED]──► db_node ──► formatter_node ──► Response
                    └─[PASSTHRU]► ai_agent_node
                                    └─► parse_output_node
                                          ├─[JSON found]──► db_node ──► formatter_node
                                          └─[no JSON]─────► formatter_node
```

Shared utilities in `app/core/`:
- **config.py** — one `Settings` class, one `.env` file
- **database.py** — one `execute_sp(query)` function works for any SP
- **memory.py** — one session store, all agents share it
- **graph_utils.py** — `AgentState`, LLM factory, JSON extractor,
  `build_standard_graph()` — each agent calls this with its own nodes

---

## Adding the Next 8 Agents

For each remaining agent zip (leads, opportunities, orders, products,
activities, notifications, accounting, analytics):

### 1. Create the agent package
```
app/agents/<name>/
    __init__.py
    prompt.py        ← Copy & keep domain-specific prompt as-is
    pre_router.py    ← Copy & keep domain-specific routing as-is
    sql_builder.py   ← Copy & keep domain-specific SP builder as-is
    formatter.py     ← Copy & keep domain-specific formatter as-is
    graph.py         ← Use the accounts/graph.py as a template:
                       - Change imports to the new domain files
                       - Change SP call in db_node (build_X_query / execute_sp)
                       - Change graph_label
    router.py        ← Use the accounts/router.py as a template:
                       - Change ChatInput fields to match the new domain
                       - Change endpoint path (/leads-chat, etc.)
                       - Change response model fields (lead/leads, etc.)
```

### 2. Register in app/main.py (one line)
```python
from app.agents.leads.router import router as leads_router
app.include_router(leads_router)
```

### 3. Uncomment the stub in app/main.py
The stubs for all 8 remaining agents are already written in the imports
section of `app/main.py` — just uncomment the relevant line.

That is the complete merge procedure. No changes to `core/` are ever needed.

---

## Shared Core — What Is Consolidated

| Concern            | Standalone (per-agent)         | crm_agent (shared)             |
|--------------------|--------------------------------|--------------------------------|
| Settings           | `app/config.py` × 10          | `app/core/config.py` × 1      |
| DB connection      | `app/database.py` × 10        | `app/core/database.py` × 1    |
| Session memory     | `app/memory.py` × 10          | `app/core/memory.py` × 1      |
| LLM factory        | `_get_llm()` duplicated × 10  | `graph_utils._get_llm()` × 1  |
| Ollama direct call | duplicated × 10               | `graph_utils._call_ollama_direct()` × 1 |
| JSON parser        | duplicated × 10               | `graph_utils.parse_ai_json()` × 1 |
| Graph topology     | duplicated × 10               | `graph_utils.build_standard_graph()` × 1 |
| Server entrypoint  | `main.py` × 10                | `app/main.py` × 1             |

Domain-specific code (prompt, pre_router, sql_builder, formatter, graph
nodes) remains **completely isolated** inside each agent's sub-package.
