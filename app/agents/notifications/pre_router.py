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

    # ── Fallback: AI Agent ───────────────────────────────────────────────────
    return _passthru(raw, chat_input)
