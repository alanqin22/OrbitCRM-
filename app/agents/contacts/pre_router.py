"""Contact Pre-Router — Python equivalent of n8n Pre Router v3.1.

ARCHITECTURAL PRINCIPLE:
  Deterministic SQL operations → ALWAYS routed directly (no AI)
  Ambiguous / NL queries       → AI Agent fallback ONLY

v3.1 FIXES:
  - compact() helper strips None values from params before passing to routed().
    Prevents Build SQL Query from receiving explicit nulls for optional params
    (e.g. tokenExpiresHours), which previously triggered false validation errors.
  - Applied compact() to all routes.

v3.0:
  Complete rewrite. Direct routes for ALL sp_contacts modes:
    list, get_details, create, update, activities, duplicates, summary,
    merge, send_verification, verify_email.
  Legacy "search contacts:" prefix retained as alias for list mode.

ROUTING TABLE (all produce router_action=True):
  "list contacts:"          → list
  "search contacts:"        → list  (legacy typeahead alias)
  "get contact:"            → get_details
  "get details:"            → get_details  (alias)
  "create contact:"         → create
  "update contact:"         → update
  "contact activities:"     → activities
  "contact duplicates:"     → duplicates
  "contact summary:"        → summary
  "merge contacts:"         → merge
  "send verification:"      → send_verification
  "verify email:"           → verify_email
  All other messages        → Passthru → AI Agent
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


# ============================================================================
# HELPERS
# ============================================================================

def _val(v: Any) -> Optional[Any]:
    """Coerce empty string / None / undefined → None."""
    if v is None or v == '':
        return None
    return v


def _compact(d: dict) -> dict:
    """
    Strip None/undefined values from a params dict before routing.

    Prevents Build SQL Query from receiving explicit nulls for optional SP
    params that have PostgreSQL DEFAULT values (e.g. tokenExpiresHours,
    pageSize).  Mirrors the JS compact() helper in n8n pre-router v3.1.
    """
    return {k: v for k, v in d.items() if v is not None}


def _extract_uuid(s: str) -> Optional[str]:
    """Return the first UUID found in a string, or None."""
    m = UUID_RE.search(str(s or ''))
    return m.group(0) if m else None


def _build_passthru_message(raw: str, chat_input: dict) -> str:
    """Append structured chatInput fields to the message — mirrors JS passthru()."""
    current = raw
    if chat_input.get('pageSize') is not None:
        current += f", page size {chat_input['pageSize']}"
    if chat_input.get('pageNumber') is not None:
        current += f", page number {chat_input['pageNumber']}"
    return current.strip()


# ============================================================================
# ROUTER
# ============================================================================

def route_request(message: str, chat_input: dict) -> Dict[str, Any]:
    """
    Inspect the incoming message and return a routing decision dict.

    Routed (deterministic direct SP call):
        { "router_action": True, "params": { "mode": "...", ... } }

    Passthru (AI Agent handles):
        { "router_action": False, "current_message": "<string>" }
    """
    raw = (message or '').strip()
    msg = raw.lower()

    logger.info('=== Contact Pre-Router v3.1 ===')
    logger.info(f'Message: {raw[:120]}')

    def routed(params: dict) -> dict:
        logger.info(
            f'→ ROUTED: mode={params.get("mode")} | '
            f'{str(params)[:200]}'
        )
        return {'router_action': True, 'params': params}

    def passthru() -> dict:
        current = _build_passthru_message(raw, chat_input)
        logger.info(f'→ PASSTHRU: AI Agent | currentMessage: {current[:120]}')
        return {'router_action': False, 'current_message': current}

    # ── List Contacts ─────────────────────────────────────────────────────────
    # Source: actions.listContacts(), goBack, pagination, home search bar
    # Prefix: "list contacts:"
    if msg.startswith('list contacts:'):
        logger.info(f'[list] pageNumber={chat_input.get("pageNumber")} '
                    f'pageSize={chat_input.get("pageSize")} '
                    f'search={chat_input.get("search")}')
        return routed(_compact({
            'mode':       'list',
            'pageNumber': _val(chat_input.get('pageNumber')) or 1,
            'pageSize':   _val(chat_input.get('pageSize'))   or 50,
            'search':     _val(chat_input.get('search')),
            'status':     _val(chat_input.get('status')),
            'accountId':  _val(chat_input.get('accountId')),
            'ownerId':    _val(chat_input.get('ownerId')),
            'dateFrom':   _val(chat_input.get('dateFrom')),
            'dateTo':     _val(chat_input.get('dateTo')),
        }))

    # ── Search Contacts (legacy typeahead alias) ───────────────────────────────
    # Source: searchContactsDirect()
    # Prefix: "search contacts:"  (search term is remainder of message)
    if msg.startswith('search contacts:'):
        query = raw[len('search contacts:'):].strip()
        if len(query) >= 2:
            logger.info(f'[list/search] query: {query}')
            return routed(_compact({
                'mode':       'list',
                'search':     query,
                'pageSize':   _val(chat_input.get('pageSize'))   or 20,
                'pageNumber': _val(chat_input.get('pageNumber')) or 1,
            }))
        logger.warning(f'[list/search] query too short ("{query}") — passthru')
        return passthru()

    # ── Get Contact Detail ────────────────────────────────────────────────────
    # Sources: viewContactDetail() → "get contact:", fetchContactGetMode() → "get contact:" / "get details:"
    if msg.startswith('get contact:') or msg.startswith('get details:'):
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        email      = _val(chat_input.get('email'))

        if contact_id or email:
            logger.info(f'[get_details] contactId={contact_id} email={email}')
            return routed(_compact({'mode': 'get_details', 'contactId': contact_id, 'email': email}))
        logger.warning('[get_details] no contactId/email — passthru')
        return passthru()

    # ── Create Contact ────────────────────────────────────────────────────────
    # Source: submitCreateContact()
    # Prefix: "create contact:"
    if msg.startswith('create contact:'):
        if not chat_input.get('firstName') and not chat_input.get('lastName'):
            logger.warning('[create] Missing firstName and lastName — passthru')
            return passthru()

        logger.info(f'[create] firstName={chat_input.get("firstName")} '
                    f'lastName={chat_input.get("lastName")} '
                    f'email={chat_input.get("email")}')

        return routed(_compact({
            'mode':            'create',
            'firstName':       _val(chat_input.get('firstName')),
            'lastName':        _val(chat_input.get('lastName')),
            'email':           _val(chat_input.get('email')),
            'phone':           _val(chat_input.get('phone')),
            'role':            _val(chat_input.get('role')),
            'status':          _val(chat_input.get('status')),
            'accountId':       _val(chat_input.get('accountId')),
            'ownerId':         _val(chat_input.get('ownerId')),
            'createdBy':       _val(chat_input.get('createdBy')),
            'billingAddress':  chat_input.get('billingAddress')  or None,
            'shippingAddress': chat_input.get('shippingAddress') or None,
        }))

    # ── Update Contact ────────────────────────────────────────────────────────
    # Source: submitUpdateContact()
    # Prefix: "update contact:"
    if msg.startswith('update contact:'):
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)

        if not contact_id:
            logger.warning('[update] Missing contactId — passthru')
            return passthru()

        logger.info(f'[update] contactId={contact_id} '
                    f'firstName={chat_input.get("firstName")} '
                    f'email={chat_input.get("email")}')

        return routed(_compact({
            'mode':            'update',
            'contactId':       contact_id,
            'firstName':       _val(chat_input.get('firstName')),
            'lastName':        _val(chat_input.get('lastName')),
            'email':           _val(chat_input.get('email')),
            'phone':           _val(chat_input.get('phone')),
            'role':            _val(chat_input.get('role')),
            'status':          _val(chat_input.get('status')),
            'accountId':       _val(chat_input.get('accountId')),
            'ownerId':         _val(chat_input.get('ownerId')),
            'updatedBy':       _val(chat_input.get('updatedBy')),
            'billingAddress':  chat_input.get('billingAddress')  or None,
            'shippingAddress': chat_input.get('shippingAddress') or None,
        }))

    # ── Contact Activities ────────────────────────────────────────────────────
    # Source: actions.showActivities()
    # Prefix: "contact activities:"
    if msg.startswith('contact activities:'):
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        email      = _val(chat_input.get('email'))

        if contact_id or email:
            logger.info(f'[activities] contactId={contact_id} email={email}')
            return routed(_compact({'mode': 'activities', 'contactId': contact_id, 'email': email}))
        logger.warning('[activities] no identifier — passthru')
        return passthru()

    # ── Find Duplicates ───────────────────────────────────────────────────────
    # Source: actions.findDuplicates()
    # Prefix: "contact duplicates:"
    if msg.startswith('contact duplicates:'):
        logger.info('[duplicates] direct route')
        return routed({'mode': 'duplicates'})

    # ── Summary / Statistics ──────────────────────────────────────────────────
    # Source: actions.showStats()
    # Prefix: "contact summary:"
    if msg.startswith('contact summary:'):
        logger.info('[summary] direct route')
        return routed({'mode': 'summary'})

    # ── Merge Contacts ────────────────────────────────────────────────────────
    # Source: merge UI button
    # Prefix: "merge contacts:"
    if msg.startswith('merge contacts:'):
        operation = _val(chat_input.get('operation'))
        email     = _val(chat_input.get('email'))
        phone     = _val(chat_input.get('phone'))

        if operation and (email or phone):
            logger.info(f'[merge] operation={operation} email={email} phone={phone}')
            return routed(_compact({'mode': 'merge', 'operation': operation, 'email': email, 'phone': phone}))
        logger.warning('[merge] missing operation or identifier — passthru')
        return passthru()

    # ── Send Email Verification ───────────────────────────────────────────────
    # Source: actions.sendVerification()
    # Prefix: "send verification:"
    if msg.startswith('send verification:'):
        contact_id          = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        email               = _val(chat_input.get('email'))
        token_expires_hours = _val(chat_input.get('tokenExpiresHours'))

        if contact_id or email:
            logger.info(f'[send_verification] contactId={contact_id} email={email}')
            return routed(_compact({
                'mode':              'send_verification',
                'contactId':         contact_id,
                'email':             email,
                'tokenExpiresHours': token_expires_hours,
            }))
        logger.warning('[send_verification] no identifier — passthru')
        return passthru()

    # ── Verify Email Token ────────────────────────────────────────────────────
    # Source: email verification link / verify form
    # Prefix: "verify email:"
    if msg.startswith('verify email:'):
        token      = _val(chat_input.get('token'))
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)

        if token:
            logger.info(f'[verify_email] token={str(token)[:8]}...')
            return routed(_compact({'mode': 'verify_email', 'token': token, 'contactId': contact_id}))
        logger.warning('[verify_email] no token — passthru')
        return passthru()

    # ── No match — AI Agent handles ───────────────────────────────────────────
    return passthru()
