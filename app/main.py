"""Unified CRM Agent application — all 12 modules + home index dashboard.

All agent routers are registered here.  Each agent exposes its own endpoint
prefix so existing HTML frontends require zero URL changes.

v2.4.0 — Added EmailAgent module (info@agentorc.ca — SMTP/IMAP + LangGraph).
  • Endpoint: POST /email-chat
  • Health:   GET  /email-health
  • Frontend: email-chat.html
  • SMTP: mail.agentorc.ca:465 (SSL)  IMAP: mail.agentorc.ca:993 (SSL)

v2.3.0 — Added Auth module (Orbit CRM Authentication).
  • Direct DB routing — no AI agent, no LangGraph AI nodes.
  • Endpoints: POST /auth/signup, /auth/signin, /auth/signout,
               /auth/change-password, /auth/password-reset/request,
               /auth/password-reset/confirm, /auth/verify-email
  • Health:   GET  /auth-health
  • Frontend: auth.html

v2.2.0 — Added Store module (CRM Commerce View).
  • Direct SP routing — no AI agent, no LangGraph AI nodes.
  • Endpoint: POST /store-chat
  • Health:   GET  /store-health
  • Frontend: store-home.html
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.database import test_connection
from app.core.memory import active_sessions, clear_session

# -- Home dashboard (sp_home_index — direct SP, no LangGraph)
from app.agents.home.router import router as home_router

# -- All 10 AI agent routers
from app.agents.accounts.router      import router as accounts_router
from app.agents.contacts.router      import router as contacts_router
from app.agents.products.router      import router as products_router
from app.agents.orders.router        import router as orders_router
from app.agents.activities.router    import router as activities_router
from app.agents.opportunities.router import router as opportunities_router
from app.agents.accounting.router    import router as accounting_router
from app.agents.leads.router         import router as leads_router
from app.agents.analytics.router     import router as analytics_router
from app.agents.notifications.router import router as notifications_router

# -- Store module (CRM Commerce View — direct SP routing, no AI agent)
from app.agents.store.router import router as store_router

# -- Auth module (direct DB routing — no AI agent)
from app.agents.auth.router import router as auth_router

# -- Email agent (SMTP/IMAP + LangGraph)
from app.agents.email.router import router as email_router

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== CRM Agent starting up (all 12 modules + home index + auth + email) ===")
    db_ok = test_connection()
    logger.info(f"Database: {'OK' if db_ok else 'FAILED -- check DB_DSN in .env'}")

    # Start autonomous inbound-email auto-reply poller
    from app.agents.email.imap_poller import start_poller, stop_poller
    try:
        from app.agents.email.smtp_imap import EMAIL_ADDRESS
        start_poller(own_address=EMAIL_ADDRESS)
        logger.info("ImapPoller started — auto-reply active for info@agentorc.ca")
    except Exception as exc:
        logger.warning(f"ImapPoller failed to start: {exc}")

    yield

    try:
        stop_poller()
    except Exception:
        pass
    logger.info("=== CRM Agent shutting down ===")


app = FastAPI(
    title="CRM Agent",
    description=(
        "Unified CRM AI Agent -- all 12 modules on a single FastAPI server: "
        "accounts, contacts, products, orders, activities, opportunities, "
        "accounting, leads, analytics, notifications, store, auth, email. "
        "Plus /home-index for the dashboard KPI cards."
    ),
    version="2.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def normalise_path(request: Request, call_next):
    """Collapse leading double-slash (e.g. //order-chat -> /order-chat)."""
    if request.url.path.startswith("//"):
        corrected = "/" + request.url.path.lstrip("/")
        scope = dict(request.scope)
        scope["path"] = corrected
        scope["raw_path"] = corrected.encode()
        request = Request(scope, request.receive, request._send)
    return await call_next(request)


# -- Home dashboard (registered first for fast routing)
app.include_router(home_router)

# -- Register all 10 AI agent routers
app.include_router(accounts_router)
app.include_router(contacts_router)
app.include_router(products_router)
app.include_router(orders_router)
app.include_router(activities_router)
app.include_router(opportunities_router)
app.include_router(accounting_router)
app.include_router(leads_router)
app.include_router(analytics_router)
app.include_router(notifications_router)

# -- Store module (direct SP routing — no AI agent)
app.include_router(store_router)

# -- Auth module (direct DB routing — no AI agent)
app.include_router(auth_router)

# -- Email agent (SMTP/IMAP + LangGraph)
app.include_router(email_router)


@app.get("/auth.html")
async def serve_auth_html():
    """Serve auth.html so email verification redirect works at http://localhost:8000/auth.html"""
    return FileResponse("auth.html", media_type="text/html")


@app.get("/")
async def root():
    return {
        "status":  "healthy",
        "service": "CRM Agent",
        "version": "2.4.0",
        "agents":  [
            "accounts", "contacts", "products", "orders",
            "activities", "opportunities", "accounting", "leads",
            "analytics", "notifications", "store", "auth", "email",
        ],
        "endpoints": {
            "home_index":    "GET /home-index",
            "accounts":      "/account-chat",
            "contacts":      "/contact-chat",
            "products":      "/prod-chat",
            "orders":        "/order-chat  (alias: /orders-chat)",
            "activities":    "/activity-chat",
            "opportunities": "/opportunity-chat",
            "accounting":    "/accounting-chat",
            "leads":         "/lead-chat  (alias: /leads-chat)",
            "analytics":     "/analytics-chat",
            "notifications": "/notifications-chat  (alias: /notification-chat)",
            "store":         "/store-chat  (direct SP — no AI agent)",
            "auth":          "/auth/signin, /auth/signup, /auth/signout, ...",
            "email":         "/email-chat  (SMTP/IMAP + LangGraph)",
        },
    }


@app.get("/health")
async def health():
    """Aggregate health check — home index + all 11 modules."""
    from app.agents.accounts.graph      import get_graph as ga
    from app.agents.contacts.graph      import get_graph as gc
    from app.agents.products.graph      import get_graph as gp
    from app.agents.orders.graph        import get_graph as go
    from app.agents.activities.graph    import get_graph as gact
    from app.agents.opportunities.graph import get_graph as gopp
    from app.agents.accounting.graph    import get_graph as gacc
    from app.agents.leads.graph         import get_graph as gl
    from app.agents.analytics.graph     import get_graph as gan
    from app.agents.notifications.graph import get_graph as gno
    from app.agents.store.graph         import get_graph as gstore
    return {
        "status":  "healthy",
        "version": "2.2.0",
        "home_index": {"endpoint": "GET /home-index", "sp": "sp_home_index"},
        "agents": {
            "accounts":      {"graph_ready": ga()     is not None},
            "contacts":      {"graph_ready": gc()     is not None},
            "products":      {"graph_ready": gp()     is not None},
            "orders":        {"graph_ready": go()     is not None},
            "activities":    {"graph_ready": gact()   is not None},
            "opportunities": {"graph_ready": gopp()   is not None},
            "accounting":    {"graph_ready": gacc()   is not None},
            "leads":         {"graph_ready": gl()     is not None},
            "analytics":     {"graph_ready": gan()    is not None},
            "notifications": {"graph_ready": gno()    is not None},
            "store":         {"graph_ready": gstore() is not None,
                              "ai_agent": False, "direct_sp": True},
        },
        "memory_window_size": settings.memory_window_size,
        "auth": {
            "graph_ready": True,
            "ai_agent": False,
            "direct_db": True,
            "endpoints": [
                "POST /auth/signup", "POST /auth/signin", "POST /auth/signout",
                "POST /auth/change-password",
                "POST /auth/password-reset/request",
                "POST /auth/password-reset/confirm",
                "POST /auth/verify-email",
            ],
        },
    }


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    clear_session(session_id)
    return {"status": "cleared", "session_id": session_id}


@app.get("/sessions")
async def list_sessions():
    return {"sessions": active_sessions()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
