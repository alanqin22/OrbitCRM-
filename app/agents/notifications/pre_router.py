"""Notifications Pre-Router v2.0 — Python conversion of n8n 'Code in JavaScript' node.

OVERVIEW
  Inspects every incoming request and either ROUTES it directly to the SQL
  builder (router_action=True) OR passes it through to the AI Agent
  (router_action=False).

  All 9 SP modes are deterministic and always routed directly. The AI Agent
  is a true fallback only for free-text natural-language queries.

KEY TRIGGERS — all produce router_action=True
  ┌────────────────────────────────────────┬──────────────────────────────────┐
  │ Message prefix (chatInput.message)     │ SP mode                          │
  ├────────────────────────────────────────┼──────────────────────────────────┤
  │ "list notifications:"                  │ list  (employeeId/module/limit…) │
  │ "inspect notification:"                │ inspect_notification             │
  │ "click notification:"                  │ click                            │
  │ "mark read:"                           │ mark_read                        │
  │ "mark unread:"                         │ mark_unread                      │
  │ "mark all read:"                       │ mark_all_read                    │
  │ "mark all unread:"                     │ mark_all_unread                  │
  │ "poll notifications:"                  │ poll (employeeId required)       │
  │ "unread count:"                        │ unread_count (employeeId req.)   │
  │ All other messages                     │ Passthru → AI Agent (NL)        │
  └────────────────────────────────────────┴──────────────────────────────────┘

PAYLOAD CONTRACT  (HTML → pre-router)
  Structured calls:  body.chatInput = { message: '<prefix>:', [key: value, …] }
  AI fallback:       body.chatInput = { message: '<natural language string>' }

PASSTHRU supplement:
  Unlike other agents (which append pageSize/pageNumber), the notifications
  passthru appends employeeId to the current message so the AI Agent can
  preserve employee filter context set in the UI.

CHANGELOG
  v2.0 — Complete rewrite. Added direct routes for all 9 SP modes from HTML UI.
          Introduced routed() / passthru() helper pattern.
  v1.0 — Original release (passthru / NL normalisation only).
"""

from __future__ import annotations

import re
import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _val(v: Any) -> Optional[Any]:
    """Coerce empty string / None → None; otherwise return as-is."""
    if v is None or v == '':
        return None
    return v


def _extract_uuid(s: str) -> Optional[str]:
    m = UUID_RE.search(str(s or ''))
    return m.group(0) if m else None


def _routed(params: dict) -> dict:
    logger.info(f"→ ROUTED: mode={params.get('mode')}  params={str(params)[:250]}")
    return {'router_action': True, 'params': params}


def _passthru(raw: str, chat_input: dict) -> dict:
    current = raw
    # Preserve employee filter context (unlike other agents that append page info)
    if chat_input.get('employeeId'):
        current += f", employeeId {chat_input['employeeId']}"
    logger.info(f"→ PASSTHRU: AI Agent | currentMessage={current[:80]!r}")
    return {'router_action': False, 'current_message': current.strip()}


# ============================================================================
# MAIN ROUTER
# ============================================================================

def route_request(body: dict, chat_input: dict, session_id: str) -> dict:
    """
    Inspect the incoming request and return a routing decision.

    Routed:   { 'router_action': True,  'params': { ... } }
    Passthru: { 'router_action': False, 'current_message': str }
    """
    logger.info('=== Notifications Pre-Router v2.0 ===')
    logger.info(f'SessionId: {session_id}')

    raw = (chat_input.get('message') or body.get('message') or '').strip()
    msg = raw.lower()
    logger.info(f'Message: {raw[:120]}')

    # ── routerAction short-circuit (v3.1) ───────────────────────────────────
    # HTML direct-SP calls send routerAction=True + mode in chatInput with no
    # message text.  Detect this here before message-pattern matching so we
    # never fall through to the AI Agent (which needs Ollama / OpenAI).
    _SKIP = {'routerAction', 'message', 'sessionId', 'chatInput',
             'originalBody', 'webhookUrl', 'executionMode',
             'currentMessage', 'chatHistory'}
    if chat_input.get('routerAction') and chat_input.get('mode'):
        _params = {k: v for k, v in chat_input.items()
                   if k not in _SKIP and v is not None}
        logger.info(f'→ routerAction SHORT-CIRCUIT: mode={_params.get("mode")}')
        return {'router_action': True, 'params': _params}

    # ── "list notifications:" ────────────────────────────────────────────────
    if msg.startswith('list notifications:'):
        logger.info(
            f"[list] employeeId={chat_input.get('employeeId')} "
            f"module={chat_input.get('module')} "
            f"limit={chat_input.get('limit')} "
            f"search={chat_input.get('search')}"
        )
        params: dict = {'mode': 'list'}
        if _val(chat_input.get('employeeId')): params['employeeId'] = _val(chat_input['employeeId'])
        if _val(chat_input.get('module')):     params['module']     = _val(chat_input['module'])
        if _val(chat_input.get('limit')):      params['limit']      = int(chat_input['limit'])
        if _val(chat_input.get('offset')):     params['offset']     = int(chat_input['offset'])
        if _val(chat_input.get('search')):     params['search']     = _val(chat_input['search'])
        return _routed(params)

    # ── "inspect notification:" ──────────────────────────────────────────────
    if msg.startswith('inspect notification:'):
        notification_id = _val(chat_input.get('notificationId')) or _extract_uuid(raw)
        if not notification_id:
            logger.warning('[inspect_notification] Missing notificationId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f'[inspect_notification] notificationId={notification_id}')
        return _routed({'mode': 'inspect_notification', 'notificationId': notification_id})

    # ── "click notification:" ────────────────────────────────────────────────
    if msg.startswith('click notification:'):
        notification_id = _val(chat_input.get('notificationId')) or _extract_uuid(raw)
        if not notification_id:
            logger.warning('[click] Missing notificationId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f'[click] notificationId={notification_id}')
        return _routed({'mode': 'click', 'notificationId': notification_id})

    # ── "mark read:" ─────────────────────────────────────────────────────────
    if msg.startswith('mark read:'):
        notification_id = _val(chat_input.get('notificationId')) or _extract_uuid(raw)
        if not notification_id:
            logger.warning('[mark_read] Missing notificationId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f'[mark_read] notificationId={notification_id}')
        return _routed({'mode': 'mark_read', 'notificationId': notification_id})

    # ── "mark unread:" ───────────────────────────────────────────────────────
    if msg.startswith('mark unread:'):
        notification_id = _val(chat_input.get('notificationId')) or _extract_uuid(raw)
        if not notification_id:
            logger.warning('[mark_unread] Missing notificationId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f'[mark_unread] notificationId={notification_id}')
        return _routed({'mode': 'mark_unread', 'notificationId': notification_id})

    # ── "mark all read:" ─────────────────────────────────────────────────────
    if msg.startswith('mark all read:'):
        logger.info(f"[mark_all_read] employeeId={chat_input.get('employeeId')}")
        p: dict = {'mode': 'mark_all_read'}
        if _val(chat_input.get('employeeId')): p['employeeId'] = _val(chat_input['employeeId'])
        return _routed(p)

    # ── "mark all unread:" ───────────────────────────────────────────────────
    if msg.startswith('mark all unread:'):
        logger.info(f"[mark_all_unread] employeeId={chat_input.get('employeeId')}")
        p = {'mode': 'mark_all_unread'}
        if _val(chat_input.get('employeeId')): p['employeeId'] = _val(chat_input['employeeId'])
        return _routed(p)

    # ── "poll notifications:" ────────────────────────────────────────────────
    if msg.startswith('poll notifications:'):
        employee_id = _val(chat_input.get('employeeId'))
        if not employee_id:
            logger.warning('[poll] Missing employeeId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f'[poll] employeeId={employee_id}')
        return _routed({'mode': 'poll', 'employeeId': employee_id})

    # ── "unread count:" ──────────────────────────────────────────────────────
    if msg.startswith('unread count:'):
        employee_id = _val(chat_input.get('employeeId'))
        if not employee_id:
            logger.warning('[unread_count] Missing employeeId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f'[unread_count] employeeId={employee_id}')
        return _routed({'mode': 'unread_count', 'employeeId': employee_id})

    # ── Executive questions (CEO / CFO / VP alert bank) ──────────────────────
    # Alert-style phrasings ("Receivable escalation", "Discounting spike") and
    # interrogatives route to the shared executive Q&A layer. Anything
    # mentioning "notification(s)" stays on the deterministic notification
    # routes below unless phrased as a question that the bank matches.
    _is_exec_candidate = (
        raw.rstrip().endswith('?')
        or bool(re.match(r'^(?:are|what|which|how|do|does|where|when|who|why|if)\b', msg))
        or 'notification' not in msg
        or bool(re.search(r'\b(alert|flag|escalation|drift|breach|spike|digest)\b', msg))
    )
    if _is_exec_candidate and raw:
        try:
            from app.agents.orchestrator.executive import match_exec_question
            _exec = match_exec_question(raw)
        except Exception:
            _exec = None
        if _exec:
            _sections, _note = _exec
            logger.info(f'[executive] sections={_sections}')
            return _routed({'mode': 'executive_question',
                            'sections': _sections, 'note': _note})

    # ── Natural-language shortcuts (v3.0) ────────────────────────────────────
    # Deterministic routing for typed / voice queries so the AI Agent is a
    # true last resort. Combinable: module + read-status + employee name +
    # search term + date window + page.
    if re.search(r'\bnotifications?\b', msg) or re.search(r'\bunread\s+count\b', msg) \
       or re.match(r'^mark\s+all\b', msg):

        # Vague single-notification actions → AI asks for the notification ID
        if re.match(r'^(?:mark|set)\s+(?:a\s+|the\s+)?notification\s+(?:as\s+)?(?:read|unread)\s*$', msg) \
           or re.match(r'^inspect\s+(?:a\s+|the\s+)?notification\s*$', msg):
            logger.info('[NL] vague single-notification action — passthru to AI')
            return _passthru(raw, chat_input)

        # "mark all [notifications] [as] read/unread [for <employee>]"
        m = re.match(
            r'^mark\s+all(?:\s+notifications?)?\s+(?:as\s+)?(read|unread)'
            r'(?:\s+for\s+(.+?))?\s*$', msg)
        if m:
            p: dict = {'mode': f'mark_all_{m.group(1)}'}
            if m.group(2):
                p['employeeName'] = raw[m.start(2):m.end(2)].strip().rstrip('?.!,')
            elif _val(chat_input.get('employeeId')):
                p['employeeId'] = _val(chat_input['employeeId'])
            logger.info(f"[NL] → {p['mode']} {p.get('employeeName', '')}")
            return _routed(p)

        # "unread count for <name>" / "how many unread notifications does <name> have"
        if re.search(r'\bunread\s+count\b', msg) or re.search(r'\bhow\s+many\s+unread\b', msg):
            name_m = re.search(r"\b(?:for|does)\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*)", raw)
            if name_m:
                logger.info(f'[NL] → unread_count for {name_m.group(1)!r}')
                return _routed({'mode': 'unread_count', 'employeeName': name_m.group(1).strip()})
            logger.info('[NL] unread count without employee — passthru to AI')
            return _passthru(raw, chat_input)

        # "search notifications for/about <term>"
        sm = re.match(r'^search\s+notifications?\s+(?:for|about|containing|mentioning)\s+(.+?)\s*$', msg)
        if sm:
            term = raw[sm.start(1):sm.end(1)].strip().rstrip('?.!,')
            logger.info(f'[NL] → list search={term!r}')
            return _routed({'mode': 'list', 'search': term, 'limit': 50})

        # ── Master list parser ────────────────────────────────────────────
        params: dict = {'mode': 'list'}
        today = date.today()

        mod_m = re.search(
            r'\b(account|contact|contract|invoice|lead|opportunit(?:y|ies)|order|payment|product|activit(?:y|ies))s?\b',
            msg)
        if mod_m:
            _mod = mod_m.group(1)
            if _mod.startswith('opportunit'):
                params['module'] = 'opportunity'
            elif _mod.startswith('activit'):
                params['module'] = 'activity'
            else:
                params['module'] = _mod

        # Event adjective directly before "notifications":
        # "invoice paid notifications", "order shipped notifications"
        ev_m = re.search(r'\b(paid|created|updated|deleted|shipped|received|completed|cancelled|overdue)\s+notifications?\b', msg)
        if ev_m:
            params['search'] = ev_m.group(1)

        # DB stores 'pending' (rendered as Unread in the UI) and 'read'
        if re.search(r'\bunread\b', msg):
            params['status'] = 'pending'
        elif re.search(r'\bread\b', msg):
            params['status'] = 'read'

        # "about <Name/term>" content search
        about_m = re.search(r'\babout\s+(.+?)\s*$', msg)
        if about_m and 'search' not in params:
            params['search'] = raw[about_m.start(1):about_m.end(1)].strip().rstrip('?.!,')

        # Trailing employee name: "… for Sarah Johnson"
        name_m = re.search(r"\bfor\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*)\s*$", raw)
        if name_m:
            params['employeeName'] = name_m.group(1).strip().rstrip('?.!,')

        page_m = re.search(r'\bpage\s+(\d+)\b', msg)
        limit_m = re.search(r'\b(?:last|recent|latest|top)\s+(\d+)\s+notifications?\b', msg)
        limit = int(limit_m.group(1)) if limit_m else 50
        params['limit'] = limit
        if page_m:
            params['offset'] = (int(page_m.group(1)) - 1) * limit

        if re.search(r'\btoday\b|\btoday.s\b', msg):
            params['dateFrom'] = params['dateTo'] = today.isoformat()
        elif re.search(r'\byesterday\b', msg):
            y = today - timedelta(days=1)
            params['dateFrom'] = params['dateTo'] = y.isoformat()
        elif re.search(r'\bthis\s+week\b', msg):
            params['dateFrom'] = (today - timedelta(days=today.weekday())).isoformat()
            params['dateTo'] = today.isoformat()
        elif re.search(r'\bthis\s+month\b|\bthis\s+month.s\b', msg):
            params['dateFrom'] = today.replace(day=1).isoformat()
            params['dateTo'] = today.isoformat()
        elif re.search(r'\blast\s+month\b', msg):
            first_this = today.replace(day=1)
            last_end = first_this - timedelta(days=1)
            params['dateFrom'] = last_end.replace(day=1).isoformat()
            params['dateTo'] = last_end.isoformat()
        elif re.search(r'\blast\s+week\b', msg):
            start = today - timedelta(days=today.weekday() + 7)
            params['dateFrom'] = start.isoformat()
            params['dateTo'] = (start + timedelta(days=6)).isoformat()

        logger.info(f'[NL-master] → list {params}')
        return _routed(params)

    # ── Fallback: AI Agent ───────────────────────────────────────────────────
    return _passthru(raw, chat_input)
