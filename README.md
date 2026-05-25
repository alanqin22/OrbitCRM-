# Orbit CRM — AI-Powered CRM with Conversational Agents

> ### 🚀 **Live Demo → [agentorc.ca](https://agentorc.ca/)**
>
> No signup required. Drop into any module and talk to the AI agents
> directly, or use the inline forms — same experience either way.

Orbit CRM is a full-stack AI CRM where every module is a **conversational
agent**: ask in plain English, get the answer (and the chart), no menus
to hunt through.

### What you can try in the live demo

_Listed in the same order as the launcher page on [agentorc.ca](https://agentorc.ca/) — start at Store Home, work clockwise through the planets, end at the Orchestrator._

| Module | What to ask / try |
|---|---|
| 🛒 Store | **CRM Universe Hub** — the landing page. KPI tiles for Active Pipeline / Open Leads / Pending Orders / Unread Alerts, plus the module launcher |
| 🎯 Leads | _"convert Maria's lead"_ — inline forms appear on vague intent; one-click conversion to opportunity |
| 👤 Accounts | _"find Apple"_, _"new prospect account"_ — voice typeahead, account-type and industry analytics |
| 📇 Contacts | _"show me Bob Brown's contact details"_ — duplicate detection, account roll-up |
| 💼 Opportunities | _"add product to opportunity"_ — stage pipeline, weighted forecast, AI-driven win probability |
| 📦 Products | _"low stock under 70"_, _"bulk stock adjustment"_, _"price history for Lenovo"_ — wholesale-≤-retail enforced at DB level |
| 📑 Orders | _"create order for ABC Corp"_ — line-item editor, status workflow, invoice generation |
| 💰 Accounting | _"Accounting Summary"_ — AR aging, cashflow, account-margin analytics, product profitability, forecast accuracy — all real-time |
| 📝 Activities | _"create task for Bob tomorrow"_ — typeahead Related-Name lookup across every entity |
| 📊 Analytics | KPI dashboards driven by Postgres stored procedures, rendered with Chart.js |
| 🔔 Notifications | Real-time activity stream with unread/read state |
| 📧 Email | Outbound mail + inbox + autonomous inbound auto-reply (SMTP/IMAP + LangGraph) |
| 🧭 Orchestrator | One launcher to talk to every agent in natural language — voice survives back/forward navigation |

### Why it's interesting

- **10 conversational AI agents** (Accounts, Contacts, Leads, Opportunities, Orders, Products, Activities, Notifications, Accounting, Analytics) — each a LangGraph state machine with deterministic pre-routing plus an LLM fallback.
- **5 supporting modules** — Orchestrator launcher, Email (SMTP/IMAP + LangGraph), Store (direct-SP catalogue), Auth (direct DB), Voice (Azure Speech token mint), plus a Home-Index KPI dashboard.
- **Hybrid routing** — common intents (search, list, update, delete) skip the LLM entirely for sub-second response; novel phrasings fall through to GPT-4o-mini.
- **Voice everywhere** — Azure Speech SDK (Bing-style) primary, Web Speech API fallback, with BFCache-safe cleanup across navigation.
- **Real analytics, not toys** — invoice-level cost/margin tracking, effective-dated wholesale/retail pricing, AR aging buckets, forecast attainment, data-quality badges, and a DB-level `wholesale ≤ retail` trigger.
- **Single FastAPI + LangGraph server** — zero duplicated config, one DB connection pool, shared session memory across all 15 modules.

---

## Project Structure

```
crm_agent/
├── main.py                        ← Top-level entry point
├── requirements.txt
├── .env                           ← Single config file for all agents
├── sp/                            ← PostgreSQL stored procedures
├── *-chat.html                    ← One frontend per agent (incl. orchestrator-chat.html)
└── app/
    ├── main.py                    ← FastAPI app — registers all routers
    ├── core/                      ← Shared utilities (zero duplication)
    │   ├── config.py              ← Orbit Settings (pydantic-settings)
    │   ├── database.py            ← Generic execute_sp() + test_connection()
    │   ├── memory.py              ← Shared session memory (rolling window)
    │   └── graph_utils.py         ← AgentState, LLM factory, JSON parser,
    │                                 build_standard_graph()
    └── agents/
        │  ── 10 conversational AI agents (LangGraph + pre-router + LLM) ──
        ├── accounts/         prompt | pre_router | sql_builder | formatter | graph | router
        ├── contacts/
        ├── leads/
        ├── opportunities/
        ├── orders/
        ├── products/
        ├── activities/
        ├── notifications/
        ├── accounting/
        ├── analytics/
        │  ── 5 supporting modules ──
        ├── home/                   ← sp_home_index dashboard (direct SP, no AI)
        ├── email/                  ← SMTP/IMAP + LangGraph + autonomous auto-reply poller
        ├── store/                  ← Commerce catalogue view (direct SP, no AI)
        ├── auth/                   ← Signup / signin / password-reset (direct DB, no AI)
        └── voice/                  ← Azure Cognitive Services token mint for browser STT
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

| Method | Path                         | Description                                    |
|--------|------------------------------|------------------------------------------------|
| GET    | `/`                          | Service info + endpoint catalogue              |
| GET    | `/health`                    | Aggregate health check (all modules + DB)      |
| GET    | `/home-index`                | Home dashboard KPIs (direct SP)                |
| POST   | `/account-chat`              | Accounts agent                                 |
| POST   | `/contact-chat`              | Contacts agent                                 |
| POST   | `/lead-chat` (`/leads-chat`) | Leads agent                                    |
| POST   | `/opportunity-chat`          | Opportunities agent                            |
| POST   | `/order-chat` (`/orders-chat`)| Orders agent                                  |
| POST   | `/prod-chat`                 | Products agent                                 |
| POST   | `/activity-chat`             | Activities agent                               |
| POST   | `/notifications-chat`        | Notifications agent                            |
| POST   | `/accounting-chat`           | Accounting agent                               |
| POST   | `/analytics-chat`            | Analytics agent                                |
| POST   | `/email-chat`                | Email agent (SMTP/IMAP + LangGraph)            |
| POST   | `/store-chat`                | Store catalogue (direct SP)                    |
| POST   | `/auth/{signin\|signup\|signout\|...}` | Auth (direct DB, no AI)              |
| GET    | `/voice/azure-token`         | Azure Speech short-lived token for browser STT |
| GET    | `/sessions`                  | List active memory sessions                    |
| DELETE | `/sessions/{id}`             | Clear a session's memory                       |

Each AI agent also exposes a matching `GET /<name>-health` endpoint that
returns `graph_ready: true/false` so a load balancer can verify the agent's
LangGraph compiled cleanly on boot.

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

## Adding a New Agent

The 10 conversational agents are all in place. To add an 11th:

### 1. Create the agent package
```
app/agents/<name>/
    __init__.py
    prompt.py        ← Domain-specific system prompt
    pre_router.py    ← Deterministic intent matchers (form-marker pattern supported)
    sql_builder.py   ← build_<name>_query()  → sp_<name>(...) call
    formatter.py     ← format_response()     → markdown the frontend renders
    graph.py         ← LangGraph nodes; call build_standard_graph()
    router.py        ← FastAPI POST /<name>-chat + GET /<name>-health
```

### 2. Register in app/main.py
```python
from app.agents.<name>.router import router as <name>_router
app.include_router(<name>_router)
```

No changes to `app/core/` are ever needed — the shared utilities work for any agent.

---

## Shared Core — What Is Consolidated

All 15 modules pull from `app/core/` rather than duplicating boilerplate.

| Concern            | Per-agent duplicate (the old way)   | Consolidated in crm_agent              |
|--------------------|--------------------------------------|----------------------------------------|
| Settings           | `app/config.py` × 15                | `app/core/config.py` × 1              |
| DB connection      | `app/database.py` × 15              | `app/core/database.py` × 1            |
| Session memory     | `app/memory.py` × 15                | `app/core/memory.py` × 1              |
| LLM factory        | `_get_llm()` duplicated × 15        | `graph_utils._get_llm()` × 1          |
| Ollama direct call | duplicated × 15                     | `graph_utils._call_ollama_direct()` × 1 |
| JSON parser        | duplicated × 15                     | `graph_utils.parse_ai_json()` × 1     |
| Graph topology     | duplicated × 15                     | `graph_utils.build_standard_graph()` × 1 |
| Server entrypoint  | `main.py` × 15                      | `app/main.py` × 1                     |

Domain-specific code (prompt, pre_router, sql_builder, formatter, graph
nodes) remains **completely isolated** inside each agent's sub-package.
