"""Contact Pre-Router - Python equivalent of n8n Pre Router v3.2.

ARCHITECTURAL PRINCIPLE:
  Deterministic SQL operations -> ALWAYS routed directly (no AI)
  Ambiguous / NL queries       -> AI Agent fallback ONLY

v3.2: Added NL shortcut patterns to catch sendRequest() button messages
      that previously fell through to the AI Agent / Ollama.
v3.1: compact() helper strips None values before routing.
v3.0: Complete rewrite with direct routes for all sp_contacts modes.

ROUTING TABLE:
  "list contacts:"       -> list
  "search contacts:"     -> list (alias)
  "get contact:"         -> get_details
  "get details:"         -> get_details (alias)
  "create contact:"      -> create
  "update contact:"      -> update
  "contact activities:"  -> activities
  "contact duplicates:"  -> duplicates
  "contact summary:"     -> summary
  "merge contacts:"      -> merge
  "send verification:"   -> send_verification
  "verify email:"        -> verify_email

  NL shortcuts (v3.2):
  "send verification email..." -> send_verification (extracts UUID)
  "show all contacts" etc.     -> list
  "archived contacts" etc.     -> list (deletedOnly=True)
  "duplicate contacts" etc.    -> duplicates

  All other messages -> Passthru -> AI Agent
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


# ===========================================================================
# HELPERS
# ===========================================================================

def _val(v: Any) -> Optional[Any]:
    """Coerce empty string / None -> None."""
    if v is None or v == '':
        return None
    return v


def _compact(d: dict) -> dict:
    """Strip None values - prevents overriding SP DEFAULT params with NULL."""
    return {k: v for k, v in d.items() if v is not None}


def _extract_uuid(s: str) -> Optional[str]:
    """Return the first UUID found in a string, or None."""
    m = UUID_RE.search(str(s or ''))
    return m.group(0) if m else None


def _build_passthru_message(raw: str, chat_input: dict) -> str:
    """Append structured chatInput fields to the message."""
    current = raw
    if chat_input.get('pageSize') is not None:
        current += f", page size {chat_input['pageSize']}"
    if chat_input.get('pageNumber') is not None:
        current += f", page number {chat_input['pageNumber']}"
    return current.strip()


# ===========================================================================
# ROUTER
# ===========================================================================

def route_request(message: str, chat_input: dict) -> Dict[str, Any]:
    """
    Inspect the incoming message and return a routing decision dict.

    Routed:   { "router_action": True,  "params": { "mode": "...", ... } }
    Passthru: { "router_action": False, "current_message": "<string>" }
    """
    raw = (message or '').strip()
    msg = raw.lower()

    logger.info('=== Contact Pre-Router v3.2 ===')
    logger.info(f'Message: {raw[:120]}')

    def routed(params: dict) -> dict:
        logger.info(
            f'-> ROUTED: mode={params.get("mode")} | {str(params)[:200]}'
        )
        return {'router_action': True, 'params': params}

    def passthru() -> dict:
        current = _build_passthru_message(raw, chat_input)
        logger.info(f'-> PASSTHRU: AI Agent | currentMessage: {current[:120]}')
        return {'router_action': False, 'current_message': current}

    # -- List Contacts ---------------------------------------------------------
    if msg.startswith('list contacts:'):
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

    # -- Search Contacts (legacy typeahead alias) ------------------------------
    if msg.startswith('search contacts:'):
        query = raw[len('search contacts:'):].strip()
        if len(query) >= 2:
            return routed(_compact({
                'mode':       'list',
                'search':     query,
                'pageSize':   _val(chat_input.get('pageSize'))   or 20,
                'pageNumber': _val(chat_input.get('pageNumber')) or 1,
            }))
        return passthru()

    # -- Get Contact Detail ----------------------------------------------------
    if msg.startswith('get contact:') or msg.startswith('get details:'):
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        email      = _val(chat_input.get('email'))
        if contact_id or email:
            logger.info(f'[get_details] contactId={contact_id} email={email}')
            return routed(_compact({'mode': 'get_details', 'contactId': contact_id, 'email': email}))
        return passthru()

    # -- Create Contact --------------------------------------------------------
    if msg.startswith('create contact:'):
        if not chat_input.get('firstName') and not chat_input.get('lastName'):
            logger.warning('[create] Missing firstName and lastName - passthru')
            return passthru()
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

    # -- Update Contact --------------------------------------------------------
    if msg.startswith('update contact:'):
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        if not contact_id:
            logger.warning('[update] Missing contactId - passthru')
            return passthru()
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

    # -- Contact Activities ----------------------------------------------------
    if msg.startswith('contact activities:'):
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        email      = _val(chat_input.get('email'))
        if contact_id or email:
            return routed(_compact({'mode': 'activities', 'contactId': contact_id, 'email': email}))
        return passthru()

    # -- Find Duplicates -------------------------------------------------------
    if msg.startswith('contact duplicates:'):
        return routed({'mode': 'duplicates'})

    # -- Summary / Statistics --------------------------------------------------
    if msg.startswith('contact summary:'):
        return routed({'mode': 'summary'})

    # -- Merge Contacts --------------------------------------------------------
    if msg.startswith('merge contacts:'):
        operation = _val(chat_input.get('operation'))
        email     = _val(chat_input.get('email'))
        phone     = _val(chat_input.get('phone'))
        if operation and (email or phone):
            return routed(_compact({'mode': 'merge', 'operation': operation, 'email': email, 'phone': phone}))
        return passthru()

    # -- Send Email Verification -----------------------------------------------
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
        logger.warning('[send_verification] no identifier - passthru')
        return passthru()

    # -- Verify Email Token ----------------------------------------------------
    if msg.startswith('verify email:'):
        token      = _val(chat_input.get('token'))
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        if token:
            logger.info(f'[verify_email] token={str(token)[:8]}...')
            return routed(_compact({'mode': 'verify_email', 'token': token, 'contactId': contact_id}))
        logger.warning('[verify_email] no token - passthru')
        return passthru()

    # ===========================================================================
    # NL SHORTCUTS (v3.2) -- safety net for any remaining sendRequest() NL calls
    # These catch natural-language button messages before they reach Ollama.
    # ===========================================================================

    # "Send verification email to contact ID {UUID}"
    if 'send verification email' in msg or 'verification email' in msg:
        contact_id = _val(chat_input.get('contactId')) or _extract_uuid(raw)
        email      = _val(chat_input.get('email'))
        if contact_id or email:
            logger.info(f'[NL->send_verification] contactId={contact_id} email={email}')
            return routed(_compact({
                'mode':      'send_verification',
                'contactId': contact_id,
                'email':     email,
            }))
        logger.warning('[NL->send_verification] no identifier - passthru')
        return passthru()

    # "Show all contacts" / "View contacts" / "list all contacts"
    if any(p in msg for p in (
        'show all contacts', 'view all contacts', 'list all contacts',
        'view contacts', 'show contacts',
    )):
        logger.info('[NL->list] all contacts')
        return routed({'mode': 'list', 'pageNumber': 1, 'pageSize': 50})

    # "Show archived contacts"
    if 'archived contacts' in msg or 'show archived' in msg or 'view archived' in msg:
        logger.info('[NL->list] archived contacts')
        return routed({'mode': 'list', 'pageNumber': 1, 'pageSize': 50, 'deletedOnly': True})

    # "Show duplicate contacts report" / "Check duplicates"
    if any(p in msg for p in (
        'duplicate contacts', 'duplicates report', 'check duplicates',
        'find duplicates', 'show duplicates',
    )):
        logger.info('[NL->duplicates]')
        return routed({'mode': 'duplicates'})

    # -- No match -- AI Agent handles ------------------------------------------
    return passthru()
