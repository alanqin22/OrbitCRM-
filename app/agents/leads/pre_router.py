"""Leads Pre-Router v2.0 — Python conversion of n8n 'pre router' node.

OVERVIEW
  Inspects every incoming request and either ROUTES it directly to the SQL
  builder (router_action=True) OR passes it through to the AI Agent
  (router_action=False).

  ARCHITECTURAL PRINCIPLE:
    Deterministic SQL operations → ALWAYS routed directly (no AI)
    Ambiguous / NL queries       → AI Agent fallback

KEY TRIGGERS — all produce router_action=True
  ┌──────────────────────────────────────┬───────────────────────────────────┐
  │ Message prefix (chatInput.message)   │ SP mode                           │
  ├──────────────────────────────────────┼───────────────────────────────────┤
  │ "list leads:"                        │ list  (+page/search/status/rating)│
  │ "get lead:"                          │ get   (leadId or email)           │
  │ "create lead:"                       │ create (full form fields)         │
  │ "update lead:"                       │ update (leadId + changed fields)  │
  │ "qualify lead:"                      │ qualify (leadId + optional reason)│
  │ "convert lead:"                      │ convert (leadId)                  │
  │ "pipeline leads:"                    │ pipeline (no params)              │
  │ "get employees:"                     │ list_employee (no params)         │
  │ All other messages                   │ Passthru → AI Agent (NL)         │
  └──────────────────────────────────────┴───────────────────────────────────┘

CHANGELOG
  v2.1 — Fixed employee mode name: get_employees → list_employee (matches SP).
  v2.0 — Complete rewrite. Direct routes for all SP modes from HTML UI.
          create/update forms now bypass the AI Agent entirely.
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
    logger.info('=== Leads Pre-Router v2.0 ===')
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

    # ── "list leads:" ────────────────────────────────────────────────────────
    if msg.startswith('list leads:'):
        logger.info(
            f"[list] pageNumber={chat_input.get('pageNumber')} "
            f"pageSize={chat_input.get('pageSize')} "
            f"search={chat_input.get('search')} "
            f"status={chat_input.get('status')} "
            f"rating={chat_input.get('rating')}"
        )
        return _routed({
            'mode':       'list',
            'pageNumber': _val(chat_input.get('pageNumber')) or 1,
            'pageSize':   _val(chat_input.get('pageSize'))   or 50,
            'search':     _val(chat_input.get('search')),
            'status':     _val(chat_input.get('status')),
            'rating':     _val(chat_input.get('rating')),
            'source':     _val(chat_input.get('source')),
        })

    # ── "get lead:" ──────────────────────────────────────────────────────────
    if msg.startswith('get lead:'):
        lead_id = _val(chat_input.get('leadId')) or _extract_uuid(raw)
        email   = _val(chat_input.get('email'))
        if lead_id or email:
            logger.info(f'[get] leadId={lead_id} email={email}')
            return _routed({'mode': 'get', 'leadId': lead_id, 'email': email})
        logger.warning('[get] no leadId or email — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "create lead:" ───────────────────────────────────────────────────────
    if msg.startswith('create lead:'):
        if not (chat_input.get('firstName') or chat_input.get('lastName')):
            logger.warning('[create] Missing firstName and lastName — falling through to AI Agent')
            return _passthru(raw, chat_input)

        logger.info(
            f"[create] firstName={chat_input.get('firstName')} "
            f"lastName={chat_input.get('lastName')} "
            f"company={chat_input.get('company')} "
            f"email={chat_input.get('email')}"
        )

        raw_score = _val(chat_input.get('score'))
        score = int(raw_score) if raw_score is not None else None

        return _routed({
            'mode':         'create',
            'firstName':    _val(chat_input.get('firstName')),
            'lastName':     _val(chat_input.get('lastName')),
            'company':      _val(chat_input.get('company')),
            'email':        _val(chat_input.get('email')),
            'phone':        _val(chat_input.get('phone')),
            'source':       _val(chat_input.get('source')),
            'rating':       _val(chat_input.get('rating')),
            'score':        score,
            'addressLine1': _val(chat_input.get('addressLine1')),
            'addressLine2': _val(chat_input.get('addressLine2')),
            'city':         _val(chat_input.get('city')),
            'province':     _val(chat_input.get('province')),
            'postalCode':   _val(chat_input.get('postalCode')),
            'country':      _val(chat_input.get('country')),
            'createdBy':    _val(chat_input.get('createdBy')),
        })

    # ── "update lead:" ───────────────────────────────────────────────────────
    if msg.startswith('update lead:'):
        lead_id = _val(chat_input.get('leadId')) or _extract_uuid(raw)
        if not lead_id:
            logger.warning('[update] Missing leadId — falling through to AI Agent')
            return _passthru(raw, chat_input)

        logger.info(
            f"[update] leadId={lead_id} "
            f"firstName={chat_input.get('firstName')} "
            f"email={chat_input.get('email')} "
            f"city={chat_input.get('city')}"
        )

        raw_score = _val(chat_input.get('score'))
        score = int(raw_score) if raw_score is not None else None

        return _routed({
            'mode':         'update',
            'leadId':       lead_id,
            'firstName':    _val(chat_input.get('firstName')),
            'lastName':     _val(chat_input.get('lastName')),
            'company':      _val(chat_input.get('company')),
            'email':        _val(chat_input.get('email')),
            'phone':        _val(chat_input.get('phone')),
            'source':       _val(chat_input.get('source')),
            'rating':       _val(chat_input.get('rating')),
            'score':        score,
            'addressLine1': _val(chat_input.get('addressLine1')),
            'addressLine2': _val(chat_input.get('addressLine2')),
            'city':         _val(chat_input.get('city')),
            'province':     _val(chat_input.get('province')),
            'postalCode':   _val(chat_input.get('postalCode')),
            'country':      _val(chat_input.get('country')),
            'updatedBy':    _val(chat_input.get('updatedBy')),
        })

    # ── "qualify lead:" ──────────────────────────────────────────────────────
    if msg.startswith('qualify lead:'):
        lead_id = _val(chat_input.get('leadId')) or _extract_uuid(raw)
        if lead_id:
            reason  = _val(chat_input.get('reason'))
            payload = {'reason': reason} if reason else None
            logger.info(f'[qualify] leadId={lead_id} reason={reason}')
            return _routed({'mode': 'qualify', 'leadId': lead_id, 'payload': payload})
        logger.warning('[qualify] no leadId — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "convert lead:" ──────────────────────────────────────────────────────
    if msg.startswith('convert lead:'):
        lead_id = _val(chat_input.get('leadId')) or _extract_uuid(raw)
        if lead_id:
            logger.info(f'[convert] leadId={lead_id}')
            return _routed({'mode': 'convert', 'leadId': lead_id})
        logger.warning('[convert] no leadId — falling through to AI Agent')
        return _passthru(raw, chat_input)

    # ── "pipeline leads:" ────────────────────────────────────────────────────
    if msg.startswith('pipeline leads:'):
        logger.info('[pipeline] direct route')
        return _routed({'mode': 'pipeline'})

    # ── "get employees:" ─────────────────────────────────────────────────────
    if msg.startswith('get employees:'):
        logger.info('[list_employee] direct route — returning active employee list')
        return _routed({'mode': 'list_employee'})

    # ── Fallback: AI Agent ───────────────────────────────────────────────────
    return _passthru(raw, chat_input)
