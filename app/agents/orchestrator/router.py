"""Orchestrator Agent v1.0 — server-side cross-module routing.

Previously the Orchestrator page did all routing client-side (keyword
router + symphony fan-out in JS), and /orchestrator-chat returned 404.
This module gives every client (web page, voice, API) the same brain:

  1. "company pulse" / "system overview"  → sp_orchestrator('overview')
     — one SQL round-trip gathering headline KPIs from every module.
  2. Symphony workflows (daily briefing, weekly report, …) — fans out to
     the underlying agent endpoints IN-PROCESS (httpx ASGITransport, no
     network hop) and weaves the responses into one sectioned report.
  3. Everything else — keyword-routes to the single best agent endpoint
     and passes its response through, annotated with `routedTo`.

The keyword rules mirror orchestrator-mgmt.html's sendMessage() router:
most-specific first (notifications beat 'invoice'; analytics report
names beat module keywords; bare 'account' → Accounts; sales summaries
→ Orders).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.database import execute_sp
from app.agents.orchestrator.executive import (
    match_exec_question, format_exec_answer,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# REQUEST MODEL
# ============================================================================

class OrchChatInput(BaseModel):
    message: Optional[str] = None


class OrchChatRequest(BaseModel):
    chatInput: Optional[OrchChatInput] = None
    sessionId: Optional[str] = None
    message: Optional[str] = None


# ============================================================================
# SYMPHONY WORKFLOWS — mirrors CHIP_DEFS in orchestrator-mgmt.html
# ============================================================================

def _today() -> str:
    return date.today().isoformat()


def _symphony_defs() -> Dict[str, dict]:
    t = _today()
    return {
        'daily': {
            'title': 'Daily Briefing',
            'calls': [
                ('/activity-chat', '📅', 'Activities',
                 f"Today's activities: summarise overdue tasks, upcoming meetings, and calls due today. Today is {t}."),
                ('/notifications-chat', '🔔', 'Alerts',
                 'Show unread notifications'),
                ('/opportunity-chat', '🎯', 'Pipeline',
                 'Show opportunities closing this month and any at-risk deals'),
            ],
        },
        'pipeline': {
            'title': 'Pipeline Health',
            'calls': [
                ('/opportunity-chat', '🎯', 'Opportunities',
                 'Pipeline health: list open opportunities by stage with expected close dates and amounts'),
                ('/lead-chat', '🌟', 'Leads', 'list leads:'),
            ],
        },
        'followup': {
            'title': 'Follow-ups Due',
            'calls': [
                ('/activity-chat', '📅', 'Overdue Activities',
                 'Show overdue activities'),
                ('/lead-chat', '🌟', 'Leads', 'list leads:'),
            ],
        },
        'revenue': {
            'title': 'Revenue Snapshot',
            'calls': [
                ('/order-chat', '📦', 'Orders', 'Sales summary this month'),
                ('/accounting-chat', '💳', 'Accounting', 'accounting summary'),
            ],
        },
        'alerts': {
            'title': 'System Alerts',
            'calls': [
                ('/notifications-chat', '🔔', 'Notifications',
                 'Show unread notifications from this week'),
            ],
        },
        'weekly': {
            'title': 'Weekly Report',
            'calls': [
                ('/activity-chat', '📅', 'Activities',
                 'Show activities created last week'),
                ('/opportunity-chat', '🎯', 'Pipeline',
                 'Show opportunities created or updated in the past 7 days'),
                ('/accounting-chat', '💳', 'Revenue', 'accounting summary'),
            ],
        },
        'team': {
            'title': 'Team Activity',
            'calls': [
                ('/activity-chat', '📅', 'Activities by Rep',
                 f'Team activity: show activities grouped by sales representative for this week. Today is {t}.'),
                ('/lead-chat', '🌟', 'Leads', 'list leads:'),
            ],
        },
        'newbiz': {
            'title': 'New Business',
            'calls': [
                ('/lead-chat', '🌟', 'Leads', 'list leads:'),
                ('/opportunity-chat', '🎯', 'New Opportunities',
                 f'Show opportunities created this month. Today is {t}.'),
            ],
        },
    }


# Symphony phrase detection — revenue narrowed to "snapshot" phrasings so
# "revenue summary for 2025" still reaches the Accounting agent's
# deterministic year/quarter parsing.
_SYMPHONY_PATTERNS = [
    ('daily',    r'daily\s*brief|morning\s*brief|daily\s*summary|start\s*of\s*day'),
    ('pipeline', r'pipeline\s*(health|status|check|review)|health.*pipeline'),
    ('followup', r'follow.?ups?\s*(due|pending|overdue)?$|overdue\s*follow.?ups?'),
    ('revenue',  r'revenue\s*snap(shot)?|financial\s*snap'),
    ('alerts',   r'system\s*alerts?$'),
    ('weekly',   r'weekly\s*(report|summary|brief|review)|week\s*in\s*review'),
    ('team',     r'team\s*activit|team\s*(report|summary|performance|breakdown)'),
    ('newbiz',   r'new\s*business|new\s*biz'),
]

_PULSE_RE = re.compile(
    r'company\s+pulse|system\s+overview|company\s+overview|crm\s+overview|\bpulse\b',
    re.IGNORECASE)


def _route_single(lower: str) -> str:
    """Keyword router — mirrors orchestrator-mgmt.html sendMessage()."""
    if re.search(r'notif|unread|\balerts?\b', lower):
        return '/notifications-chat'
    if re.search(r'cash\s*flow|lead\s+sources?|owner\s+breakdown|productivity'
                 r'|invoiced\s+revenue|ar\s+age?ing|analytic|forecast|dashboard', lower):
        return '/analytics-chat'
    if re.search(r'lead|prospect|conver', lower):
        return '/lead-chat'
    if re.search(r'opportunit|deal|pipeline|stage|win\s*rate', lower):
        return '/opportunity-chat'
    if re.search(r'order|fulfil|ship|sales\s+(summary|by)', lower):
        return '/order-chat'
    if re.search(r'invoic|payment|accounting|revenue|cash', lower):
        return '/accounting-chat'
    if re.search(r'contact|person|people', lower):
        return '/contact-chat'
    if re.search(r'account|company|compan', lower):
        return '/account-chat'
    if re.search(r'product|catalogue|inventor|stock', lower):
        return '/prod-chat'   # NB: the Products agent route is /prod-chat
    if re.search(r'email|message|outreach', lower):
        return '/email-chat'
    return '/activity-chat'


# ============================================================================
# IN-PROCESS AGENT CALLS (ASGI — no network hop)
# ============================================================================

async def _call_agent(path: str, message: str, session_id: str) -> dict:
    from app.main import app as _app  # lazy import avoids a circular import
    transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url='http://orchestrator.internal',
                                 timeout=300) as client:
        resp = await client.post(path, json={
            'sessionId': session_id,
            'chatInput': {'message': message},
        })
        try:
            data = resp.json()
        except Exception:
            return {'output': resp.text[:2000], 'mode': 'raw'}
        if isinstance(data, list):
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {'output': str(data)[:2000]}


# ============================================================================
# FORMATTERS
# ============================================================================

def _fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _format_pulse(result: dict) -> str:
    a  = result.get('activities', {})
    n  = result.get('notifications', {})
    o  = result.get('opportunities', {})
    l  = result.get('leads', {})
    od = result.get('orders', {})
    iv = result.get('invoices', {})
    pm = result.get('payments', {})
    ac = result.get('accounts', {})
    pr = result.get('products', {})

    out = [
        '### 💓 Company Pulse',
        f"**As of:** {str(result.get('metadata', {}).get('as_of', ''))[:16]}",
        '',
        '| Module | Headline Metrics |',
        '| --- | --- |',
        f"| 🎯 Opportunities | **{o.get('open_count', 0)}** open worth **{_fmt_money(o.get('open_value', 0))}** · {o.get('closing_this_month', 0)} closing this month |",
        f"| 📦 Orders | **{od.get('this_month_count', 0)}** this month · revenue **{_fmt_money(od.get('this_month_revenue', 0))}** · {od.get('pending', 0)} pending |",
        f"| 🧾 Invoices | **{_fmt_money(iv.get('outstanding_total', 0))}** outstanding · {iv.get('overdue_count', 0)} past due |",
        f"| 💳 Payments | **{_fmt_money(pm.get('this_month_total', 0))}** received this month |",
        f"| 🌟 Leads | **{l.get('total', 0)}** total · {l.get('new_this_week', 0)} new this week |",
        f"| 📅 Activities | **{a.get('overdue', 0)}** overdue · {a.get('due_today', 0)} due today · {a.get('total', 0)} total |",
        f"| 🔔 Notifications | **{n.get('unread', 0)}** unread |",
        f"| 🏢 Accounts | **{ac.get('active', 0)}** active |",
        f"| 🛒 Products | **{pr.get('active', 0)}** active · {pr.get('low_stock', 0)} low stock |",
        '',
        '*Powered by sp_orchestrator — all modules in one query.*',
    ]
    return '\n'.join(out)


def _weave_symphony(title: str, calls: List[tuple], results: List[Any]) -> str:
    out = [f'### ⚙️ {title}',
           f'*{len(calls)} agents queried by the Orchestrator*', '']
    for (path, icon, label, _msg), res in zip(calls, results):
        out.append('---')
        out.append(f'### {icon} {label}')
        if isinstance(res, Exception):
            out.append(f'_Agent unavailable: {str(res)[:120]}_')
        else:
            body = (res.get('output') or res.get('error')
                    or '_No data returned from this agent._')
            out.append(str(body))
        out.append('')
    return '\n'.join(out)


# ============================================================================
# ROUTE
# ============================================================================

@router.get('/orchestrator-health')
async def orchestrator_health():
    return {'status': 'healthy', 'module': 'orchestrator', 'version': '1.0.0'}


@router.post('/orchestrator-chat')
async def orchestrator_chat(req: OrchChatRequest):
    session_id = (req.sessionId or 'orch-session').strip()
    message = ((req.chatInput.message if req.chatInput else None)
               or req.message or '').strip()
    lower = message.lower()
    logger.info(f'=== Orchestrator Chat === {message[:100]!r}')

    if not message:
        return JSONResponse({'sessionId': session_id, 'success': False,
                             'output': 'Please provide a message.', 'mode': 'error'})

    # ── 1. Company pulse — sp_orchestrator overview ──────────────────────────
    if _PULSE_RE.search(lower):
        try:
            rows = execute_sp("SELECT sp_orchestrator('overview') AS result")
            result = rows[0].get('result') if rows else {}
            return JSONResponse({
                'sessionId': session_id, 'success': True,
                'mode': 'pulse', 'output': _format_pulse(result or {}),
            })
        except Exception as e:
            logger.error(f'pulse failed: {e}', exc_info=True)
            return JSONResponse({'sessionId': session_id, 'success': False,
                                 'mode': 'error', 'output': f'Pulse failed: {e}'})

    # ── 1b. Executive question bank (CEO / CFO / VP Finance / VP Sales) ──────
    # Matches before symphonies and single-agent routing so phrases like
    # "weighted forecast vs commit" get the executive pack, not keyword
    # routing. Out-of-CRM topics return an honest scope note + best proxy.
    exec_match = match_exec_question(message)
    if exec_match:
        sections, note = exec_match
        try:
            rows = execute_sp("SELECT sp_orchestrator('executive') AS result")
            pack = (rows[0].get('result') or {}) if rows else {}
            return JSONResponse({
                'sessionId': session_id, 'success': True,
                'mode': 'executive', 'sections': sections,
                'output': format_exec_answer(pack, sections, note),
            })
        except Exception as e:
            logger.error(f'executive pack failed: {e}', exc_info=True)
            return JSONResponse({'sessionId': session_id, 'success': False,
                                 'mode': 'error',
                                 'output': f'Executive pack failed: {e}'})

    # ── 2. Symphony workflows — multi-agent fan-out ──────────────────────────
    for key, pat in _SYMPHONY_PATTERNS:
        if re.search(pat, lower, re.IGNORECASE):
            defs = _symphony_defs()[key]
            calls = defs['calls']
            logger.info(f'[symphony] {key} → {len(calls)} agents')
            results = await asyncio.gather(
                *[_call_agent(p, m, session_id) for (p, _i, _l, m) in calls],
                return_exceptions=True)
            return JSONResponse({
                'sessionId': session_id, 'success': True,
                'mode': 'symphony', 'workflow': key,
                'output': _weave_symphony(defs['title'], calls, results),
            })

    # ── 3. Single-agent delegation ───────────────────────────────────────────
    path = _route_single(lower)
    logger.info(f'[route] → {path}')
    try:
        data = await _call_agent(path, message, session_id)
    except Exception as e:
        logger.error(f'delegation to {path} failed: {e}', exc_info=True)
        return JSONResponse({'sessionId': session_id, 'success': False,
                             'mode': 'error', 'routedTo': path,
                             'output': f'Agent call failed: {e}'})
    data = dict(data)
    data.setdefault('sessionId', session_id)
    data['routedTo'] = path
    return JSONResponse(data)
