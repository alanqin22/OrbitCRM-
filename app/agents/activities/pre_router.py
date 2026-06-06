"""Activities Pre-Router v3.0 — Python conversion of n8n 'Code in JavaScript' node.

OVERVIEW
  Inspects every incoming request message and either ROUTES it directly
  to the SQL builder (router_action=True) OR passes it through to the
  AI Agent (router_action=False).

  ARCHITECTURAL PRINCIPLE:
    Deterministic SQL operations → ALWAYS routed directly (no AI)
    Ambiguous / NL queries       → AI Agent fallback

KEY TRIGGERS — all produce router_action=True
  ┌──────────────────────────────────────┬───────────────────────────────┐
  │ Message prefix (chatInput.message)   │ SP mode                       │
  ├──────────────────────────────────────┼───────────────────────────────┤
  │ "list activities:"                   │ list                          │
  │ "overdue activities:"                │ overdue                       │
  │ "upcoming activities:"               │ upcoming                      │
  │ "activity summary:"                  │ summary                       │
  │ "activity timeline:"                 │ timeline                      │
  │ "get activity:"                      │ get                           │
  │ "create activity:"                   │ create                        │
  │ "update activity:"                   │ update                        │
  │ "complete activity:"                 │ complete                      │
  │ "reopen activity:"                   │ reopen                        │
  │ "delete activity:"                   │ delete                        │
  │ "get owners:"                        │ get_owners                    │
  │ All other messages                   │ Passthru → AI Agent (NL)      │
  └──────────────────────────────────────┴───────────────────────────────┘

CHANGELOG
  v3.0 — Added direct route for "get owners:" → mode get_owners.
  v2.0 — Full rewrite. Direct routes for all 11 SP modes from HTML UI.
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
    logger.info(f"→ ROUTED: mode={params.get('mode')}  params={str(params)[:200]}")
    return {'router_action': True, 'params': params}


def _passthru(raw: str, chat_input: dict) -> dict:
    current = raw
    if chat_input.get('pageSize'):   current += f", page size {chat_input['pageSize']}"
    if chat_input.get('pageNumber'): current += f", page number {chat_input['pageNumber']}"
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
    logger.info('=== Activities Pre-Router v3.0 ===')
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

    # ── "list activities:" ───────────────────────────────────────────────────
    if msg.startswith('list activities:'):
        include_completed = chat_input.get('includeCompleted')
        if include_completed is None:
            include_completed = True
        only_completed = _val(chat_input.get('onlyCompleted'))
        return _routed({
            'mode':             'list',
            'pageNumber':       _val(chat_input.get('pageNumber')) or 1,
            'pageSize':         _val(chat_input.get('pageSize'))   or 50,
            'search':           _val(chat_input.get('search')),
            'includeCompleted': include_completed,
            'onlyCompleted':    only_completed,
        })

    # ── "overdue activities:" ────────────────────────────────────────────────
    if msg.startswith('overdue activities:'):
        return _routed({'mode': 'overdue'})

    # ── "upcoming activities:" ───────────────────────────────────────────────
    if msg.startswith('upcoming activities:'):
        return _routed({'mode': 'upcoming'})

    # ── "activity summary:" ──────────────────────────────────────────────────
    if msg.startswith('activity summary:'):
        return _routed({'mode': 'summary'})

    # ── "activity timeline:" ─────────────────────────────────────────────────
    if msg.startswith('activity timeline:'):
        related_type = _val(chat_input.get('relatedType'))
        related_id   = _val(chat_input.get('relatedId'))
        if related_type and related_id:
            logger.info(f'[timeline] relatedType={related_type} relatedId={related_id}')
            return _routed({'mode': 'timeline', 'relatedType': related_type, 'relatedId': related_id})
        # No entity provided — passthru so the AI Agent can ask for a name
        logger.warning('[timeline] missing relatedType/relatedId — passthru to AI Agent')
        return _passthru(raw, chat_input)

    # ── "get activity:" ──────────────────────────────────────────────────────
    if msg.startswith('get activity:'):
        activity_id = _val(chat_input.get('activityId')) or _extract_uuid(raw)
        if activity_id:
            return _routed({'mode': 'get', 'activityId': activity_id})
        logger.warning('[get] no activityId — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "create activity:" ───────────────────────────────────────────────────
    if msg.startswith('create activity:'):
        if not (chat_input.get('relatedType') and chat_input.get('relatedId') and chat_input.get('type')):
            logger.warning('[create] Missing required fields — falling through to AI Agent')
            return _passthru(raw, chat_input)
        logger.info(f"[create] type={chat_input.get('type')} relatedType={chat_input.get('relatedType')}")
        return _routed({
            'mode':        'create',
            'relatedType': _val(chat_input.get('relatedType')),
            'relatedId':   _val(chat_input.get('relatedId')),
            'type':        _val(chat_input.get('type')),
            'subject':     _val(chat_input.get('subject')),
            'description': _val(chat_input.get('description')),
            'dueDate':     _val(chat_input.get('dueDate')),
            'direction':   _val(chat_input.get('direction')),
            'channel':     _val(chat_input.get('channel')),
            'ownerId':     _val(chat_input.get('ownerId')),
        })

    # ── "update activity:" ───────────────────────────────────────────────────
    if msg.startswith('update activity:'):
        activity_id = _val(chat_input.get('activityId'))
        if not activity_id:
            logger.warning('[update] Missing activityId — falling through to AI Agent')
            return _passthru(raw, chat_input)
        # completedAt may be explicitly None (reopen/clear) — preserve that distinction
        completed_at = chat_input.get('completedAt', None)
        return _routed({
            'mode':        'update',
            'activityId':  activity_id,
            'subject':     _val(chat_input.get('subject')),
            'description': _val(chat_input.get('description')),
            'dueDate':     _val(chat_input.get('dueDate')),
            'direction':   _val(chat_input.get('direction')),
            'channel':     _val(chat_input.get('channel')),
            'ownerId':     _val(chat_input.get('ownerId')),
            'completedAt': completed_at,
            'relatedType': _val(chat_input.get('relatedType')),
            'relatedId':   _val(chat_input.get('relatedId')),
        })

    # ── "complete activity:" ─────────────────────────────────────────────────
    if msg.startswith('complete activity:'):
        activity_id = _val(chat_input.get('activityId')) or _extract_uuid(raw)
        if activity_id:
            return _routed({'mode': 'complete', 'activityId': activity_id})
        logger.warning('[complete] no activityId — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "reopen activity:" ───────────────────────────────────────────────────
    if msg.startswith('reopen activity:'):
        activity_id = _val(chat_input.get('activityId')) or _extract_uuid(raw)
        if activity_id:
            return _routed({'mode': 'reopen', 'activityId': activity_id})
        logger.warning('[reopen] no activityId — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "delete activity:" ───────────────────────────────────────────────────
    if msg.startswith('delete activity:'):
        activity_id = _val(chat_input.get('activityId')) or _extract_uuid(raw)
        if activity_id:
            return _routed({'mode': 'delete', 'activityId': activity_id})
        logger.warning('[delete] no activityId — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "get owners:" ────────────────────────────────────────────────────────
    if msg.startswith('get owners:'):
        logger.info('[get_owners] direct route — returning active owner list')
        return _routed({'mode': 'get_owners'})

    # ── Natural-language shortcuts ────────────────────────────────────────────
    # Catch common typed/voice queries before they reach the AI Agent, which
    # returns empty results for these well-known filter requests.

    # "pending activities" / "show pending" / "open activities" / "incomplete"
    _PENDING_RE = re.compile(
        r'\b(pending|not\s+completed?|incomplete|open)\b.*\bactivit|\bactivit.*\b(pending|open|incomplete)\b',
        re.IGNORECASE,
    )
    if _PENDING_RE.search(raw):
        logger.info('[NL] → pending activities shortcut: mode=list includeCompleted=False')
        return _routed({
            'mode':             'list',
            'includeCompleted': False,
            'pageNumber':       1,
            'pageSize':         50,
        })

    # "overdue activities" / "activities overdue" / "past due activities"
    _OVERDUE_RE = re.compile(
        r'\b(overdue|past\s+due|late)\b.*\bactivit|\bactivit.*\b(overdue|past\s+due|late)\b',
        re.IGNORECASE,
    )
    if _OVERDUE_RE.search(raw):
        logger.info('[NL] → overdue activities shortcut: mode=overdue')
        return _routed({'mode': 'overdue'})

    # "upcoming activities" / "activities this week" / "scheduled activities"
    _UPCOMING_RE = re.compile(
        r'\b(upcoming|this\s+week|scheduled|future)\b.*\bactivit|\bactivit.*\b(upcoming|this\s+week|scheduled)\b',
        re.IGNORECASE,
    )
    if _UPCOMING_RE.search(raw):
        logger.info('[NL] → upcoming activities shortcut: mode=upcoming')
        return _routed({'mode': 'upcoming'})

    # "completed activities" / "activities completed" / "finished activities"
    _COMPLETED_RE = re.compile(
        r'\b(completed?|finished?|done|closed)\b.*\bactivit|\bactivit.*\b(completed?|finished?|done|closed)\b',
        re.IGNORECASE,
    )
    if _COMPLETED_RE.search(raw):
        logger.info('[NL] → completed activities shortcut: mode=list onlyCompleted=True')
        return _routed({
            'mode':             'list',
            'includeCompleted': True,
            'onlyCompleted':    True,
            'pageNumber':       1,
            'pageSize':         50,
        })

    # "all activities" / "list all activities" / "show me activities" / "my activities"
    _ALL_RE = re.compile(
        r'\b(all|every|show\s+(me\s+)?|list\s+(all\s+)?|my\s+|get\s+)\bactivit|\bactivit\b',
        re.IGNORECASE,
    )
    if _ALL_RE.search(raw):
        logger.info('[NL] → all activities shortcut: mode=list includeCompleted=True')
        return _routed({
            'mode':             'list',
            'includeCompleted': True,
            'pageNumber':       1,
            'pageSize':         50,
        })

    # ── Fallback: AI Agent ───────────────────────────────────────────────────
    return _passthru(raw, chat_input)
