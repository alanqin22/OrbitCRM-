"""Account Pre-Router — Python equivalent of n8n Pre Router v3.0.

OVERVIEW
  Inspects every incoming message and either:
    • ROUTES directly to Build SQL Query (router_action = True)  — deterministic SP call
    • Passes through to the AI Agent   (router_action = False)   — free-text NL

  DESIGN PRINCIPLE: Every SP mode that accepts deterministic parameters
  MUST be handled here. The AI Agent is invoked ONLY as a last resort for
  free-form natural-language queries that cannot be structured here.

ROUTING TABLE
  "account direct: <mode>"              → mode:<mode>, params from chatInput fields
      Sent by all form submits and quick-action buttons in the HTML page.
      Valid modes: create | update | get | list | timeline | financials |
                   duplicates | summary | archive | restore | merge
  "search accounts: <query>"            → mode:'list', search:<query>
      Home-page and form typeahead boxes.
  "list accounts" / "list accounts: …"  → mode:'list'
      Bare list request or legacy deep-link.
  "get account: <uuid>"                 → mode:'get', account_id:<uuid>
      Update-form fetchAccountGetMode().
  "show/get details for account with uuid" → mode:'get', accountId:<uuid>
      Legacy detail-link pattern.
  All other messages                    → Passthru → AI Agent

CHANGELOG
  v3.0 — Added "account direct: <mode>" universal direct-route pattern.
         All form submits and button actions bypass the AI Agent entirely.
         Added "list accounts" bare-list direct route.
  v2.1 — Added "get account: <uuid>" direct route for Update Account form.
  v2.0 — Full rewrite to routerAction pattern; added account search route.
  v1.0 — Original passthru-only pre-router.
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)

VALID_DIRECT_MODES = {
    'create', 'update', 'get', 'list',
    'timeline', 'financials', 'duplicates', 'summary',
    'archive', 'restore', 'merge',
}

# Keys injected by the pre-router itself that must NOT be forwarded to sp_accounts
_ROUTING_ONLY = {
    'sessionId', 'chatInput', 'message', 'originalBody',
    'webhookUrl', 'executionMode', 'routerAction',
    'currentMessage', 'chatHistory',
    'mode', 'routerAction',          # prevent loop-overwrite of SP params
}


def _extract_uuids(s: str) -> list:
    return UUID_RE.findall(str(s))


def _val(v: Any) -> Any:
    """Coerce empty string / None to None."""
    if v is None or v == '':
        return None
    return v


def _build_passthru_message(raw: str, chat_input: dict) -> str:
    """Append structured chatInput fields to the message — mirrors the JS passthru() helper."""
    current = raw
    if chat_input.get('city'):
        current += f", city {chat_input['city']}"
    if chat_input.get('pageSize') is not None:
        current += f", page size {chat_input['pageSize']}"
    if chat_input.get('pageNumber') is not None:
        current += f", page number {chat_input['pageNumber']}"
    if chat_input.get('customerId'):
        current += f", customer ID {chat_input['customerId']}"
    return current.strip()


def route_request(message: str, chat_input: dict) -> Dict[str, Any]:
    """
    Inspect the incoming message and return a routing decision dict.

    Routed (deterministic direct SP call):
        {
            "router_action": True,
            "params": { "mode": "...", ... }
        }

    Passthru (AI Agent handles):
        {
            "router_action": False,
            "current_message": "<preprocessed message string>"
        }

    Parameters
    ----------
    message    : Raw message string from chatInput.message
    chat_input : Full chatInput dict (all structured fields from the web page)
    """
    raw = (message or '').strip()
    msg = raw.lower()

    logger.info('=== Account Pre-Router v3.0 ===')
    logger.info(f'Message: {raw}')

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

    def routed(params: dict) -> dict:
        logger.info(
            f'→ ROUTED: mode={params.get("mode")} '
            f'{params.get("search") or params.get("account_id") or params.get("accountId") or ""}'
        )
        return {'router_action': True, 'params': params}

    def passthru() -> dict:
        current_message = _build_passthru_message(raw, chat_input)
        logger.info(f'→ PASSTHRU: AI Agent | currentMessage: {current_message}')
        return {'router_action': False, 'current_message': current_message}

    # ── "account direct: <mode>" — universal direct-route  (v3.0) ────────────
    # Sent by submitCreateAccount(), submitUpdateAccount(), sendDirectRequest(),
    # viewAccountDetails(), and all Quick Action buttons.
    # chatInput fields (account_id, account_name, billing_address, …) are
    # forwarded into params; Build SQL Query normalises snake_case → camelCase.
    if msg.startswith('account direct:'):
        operation = raw[len('account direct:'):].strip().lower()

        if operation in VALID_DIRECT_MODES:
            # Build params: mode + every extra chatInput field (excluding routing sentinels)
            params: Dict[str, Any] = {'mode': operation}
            for key, value in chat_input.items():
                if key == 'message':
                    continue              # skip the routing sentinel itself
                if key in _ROUTING_ONLY:
                    continue
                params[key] = value
            return routed(params)

        logger.warning(f'[AccountDirect] unknown operation "{operation}" — passthru')
        return passthru()

    # ── "search accounts: <query>" — typeahead search  ───────────────────────
    # Sent by home-page and Update-form typeahead boxes.
    if msg.startswith('search accounts:'):
        query = raw[len('search accounts:'):].strip()
        page_size = int(chat_input.get('pageSize') or 20)
        page_num  = int(chat_input.get('pageNumber') or 1)

        if len(query) >= 2:
            return routed({
                'mode':       'list',
                'search':     query,
                'pageSize':   page_size,
                'pageNumber': page_num,
            })
        logger.warning(f'[AccountSearch] query too short ("{query}") — passthru')
        return passthru()

    # ── "list accounts" / "list accounts: …" — bare list  ────────────────────
    if msg == 'list accounts' or msg.startswith('list accounts:'):
        page_size = int(chat_input.get('pageSize') or 20)
        page_num  = int(chat_input.get('pageNumber') or 1)
        return routed({'mode': 'list', 'pageSize': page_size, 'pageNumber': page_num})

    # ── "get account: <uuid>" — Update-form fetchAccountGetMode()  (v2.1) ─────
    if re.match(r'^get account:\s+', raw, re.IGNORECASE):
        explicit_id = (_val(chat_input.get('account_id')) or '').strip()
        parsed_ids  = _extract_uuids(raw)
        account_id  = explicit_id or (parsed_ids[0] if parsed_ids else '')

        if account_id:
            logger.info(f'[AccountGet] accountId: {account_id}')
            return routed({'mode': 'get', 'account_id': account_id})
        logger.warning('[AccountGet] no UUID found — passthru')
        return passthru()

    # ── Legacy "show/get details for account with uuid"  ─────────────────────
    if (msg.startswith('show details for account with uuid') or
            msg.startswith('get details for account with uuid')):
        ids = _extract_uuids(raw)
        if ids:
            return routed({'mode': 'get', 'accountId': ids[0]})

    # ── No match — AI Agent handles  ─────────────────────────────────────────
    return passthru()
