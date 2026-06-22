"""Shared API authentication/authorization dependencies (security hardening #1).

Two FastAPI dependencies enforce identity at the edge of the API:

  require_admin    Protects the privileged COMMAND endpoints (agent-bus,
                   supervisor, notification-triage, governance, a2a, blackboard)
                   that can trigger mass mutations. Enforced whenever
                   ADMIN_API_TOKEN is configured — recommended in EVERY deployed
                   environment. Callers present the secret via the 'X-Admin-Token'
                   header (or 'Authorization: Bearer <token>'). The web frontend
                   never calls these endpoints, so enabling this NEVER breaks the
                   UI. Fails closed (403) once a token is set; constant-time compare.

  require_session  Protects the CRM DATA endpoints (the *-chat APIs). Validates a
                   user session issued by /auth/signin. GATED by API_AUTH_ENABLED
                   (default 0) so the current frontend keeps working until it sends
                   the session token — then flip the flag to enforce. Staged
                   rollout, mirroring the rest of this codebase.

CONFIG (env)
  ADMIN_API_TOKEN   ''   shared secret for admin/command endpoints (set a strong value)
  API_AUTH_ENABLED   0   1 = enforce user sessions on data endpoints (after the
                         frontend is updated to send 'Authorization: Bearer <token>')
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request

logger = logging.getLogger("auth_dep")


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


API_AUTH_ENABLED = _flag("API_AUTH_ENABLED")
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "").strip()

# Surface the posture once at import (startup) rather than per request.
if not ADMIN_API_TOKEN:
    logger.warning(
        "[security] ADMIN_API_TOKEN is unset — admin/command endpoints "
        "(/agent-bus, /supervisor, /notif-triage, /governance, /a2a, /blackboard) "
        "are NOT protected. Set ADMIN_API_TOKEN to lock them down."
    )
if not API_AUTH_ENABLED:
    logger.info(
        "[security] API_AUTH_ENABLED=0 — data (*-chat) endpoints accept "
        "unauthenticated calls (staged rollout; enable once the frontend sends "
        "the session token)."
    )


def _bearer(request: Request) -> Optional[str]:
    """Extract a token from 'Authorization: Bearer <t>' or 'X-Session-Token'."""
    h = request.headers.get("authorization") or ""
    if h[:7].lower() == "bearer ":
        return h[7:].strip()
    return request.headers.get("x-session-token")


# Write operations a read-only ('viewer') role may NOT perform. Keyed off the
# explicit 'mode'/'action' in the request body (the structured create/update/
# delete forms). Default-deny by listing writes; unknown/absent modes (NL reads,
# list/get/report/forecast) are allowed.
WRITE_MODES = {
    "create", "update", "delete", "edit", "save", "remove", "add",
    "change_stage", "close_won", "close_lost", "convert", "qualify", "disqualify",
    "merge", "archive", "restore", "assign", "reassign", "snooze", "complete",
    "cancel", "approve", "reject", "send",
    "add_product", "update_product", "remove_product", "update_stock", "adjust",
    "show_lead_form", "show_lead_update_form",  # forms that lead to writes
}


async def require_admin(request: Request) -> bool:
    """Gate privileged command endpoints.

    Accepts EITHER a machine/ops token (ADMIN_API_TOKEN via 'X-Admin-Token' or
    bearer) OR a logged-in session whose role is 'admin'. Fails closed (403) once
    any protection is configured; bypasses (with a startup warning) only when both
    ADMIN_API_TOKEN is unset AND API_AUTH_ENABLED=0 (local dev)."""
    # 1. machine/ops shared secret
    if ADMIN_API_TOKEN:
        provided = request.headers.get("x-admin-token") or _bearer(request) or ""
        if secrets.compare_digest(provided, ADMIN_API_TOKEN):
            return True
    # 2. human admin via session
    if API_AUTH_ENABLED:
        from app.agents.auth.router import get_session
        sess = get_session(_bearer(request) or "")
        if sess and sess.get("role") == "admin":
            request.state.session = sess
            return True
    # 3. dev bypass only when nothing is configured
    if not ADMIN_API_TOKEN and not API_AUTH_ENABLED:
        return True
    raise HTTPException(status_code=403, detail="Admin authorization required")


async def require_session(request: Request) -> Optional[Dict[str, Any]]:
    """Validate a CRM user session on data endpoints.

    No-op unless API_AUTH_ENABLED=1 (staged rollout). When enabled, requires a
    valid, non-expired session token from /auth/signin or returns 401. Stashes the
    session on request.state for downstream role checks (e.g. require_write)."""
    if not API_AUTH_ENABLED:
        return None
    # Lazy import avoids any import-order coupling with the auth router.
    from app.agents.auth.router import get_session
    token = _bearer(request)
    sess = get_session(token) if token else None
    if not sess:
        raise HTTPException(status_code=401, detail="Authentication required")
    request.state.session = sess
    return sess


async def _request_mode(request: Request) -> Optional[str]:
    """Best-effort extract of the operation 'mode'/'action' from a JSON body.
    Returns None for non-JSON / bodyless requests (treated as a read)."""
    try:
        body = await request.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    ci = body.get("chatInput") if isinstance(body.get("chatInput"), dict) else {}
    mode = body.get("mode") or body.get("action") or ci.get("mode") or ci.get("action")
    return str(mode).strip().lower() if mode else None


async def require_write(request: Request) -> None:
    """Block 'viewer' (read-only) sessions from write operations. No-op unless
    API_AUTH_ENABLED=1. admin/member pass through; viewer is rejected only when the
    request carries an explicit write mode (the structured create/update/delete
    forms)."""
    if not API_AUTH_ENABLED:
        return
    sess = getattr(request.state, "session", None)
    role = (sess or {}).get("role", "member")
    if role != "viewer":
        return
    mode = await _request_mode(request)
    if mode and mode in WRITE_MODES:
        raise HTTPException(
            status_code=403,
            detail="Read-only (viewer) role: write operations are not permitted.",
        )
