"""EmailAgent Pre-Router — maps message prefixes to SP modes."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)

_SKIP = {
    'routerAction', 'message', 'sessionId', 'chatInput',
    'originalBody', 'webhookUrl', 'executionMode',
    'currentMessage', 'chatHistory',
}


def _val(v: Any) -> Optional[Any]:
    if v is None or v == '':
        return None
    return v


def _routed(params: dict) -> dict:
    logger.info(f"→ ROUTED: mode={params.get('mode')} params={str(params)[:200]}")
    return {'router_action': True, 'params': params}


def _passthru(raw: str, chat_input: dict) -> dict:
    logger.info(f"→ PASSTHRU: AI Agent | currentMessage={raw[:80]!r}")
    return {'router_action': False, 'current_message': raw.strip()}


def route_request(body: dict, chat_input: dict, session_id: str) -> dict:
    logger.info('=== EmailAgent Pre-Router ===')
    logger.info(f'SessionId: {session_id}')

    raw = (chat_input.get('message') or body.get('message') or '').strip()
    msg = raw.lower()
    logger.info(f'Message: {raw[:120]}')

    # routerAction short-circuit (HTML direct-SP calls)
    if chat_input.get('routerAction') and chat_input.get('mode'):
        params = {k: v for k, v in chat_input.items()
                  if k not in _SKIP and v is not None}
        logger.info(f'→ routerAction SHORT-CIRCUIT: mode={params.get("mode")}')
        return {'router_action': True, 'params': params}

    if msg.startswith('check inbox:'):
        return _routed({'mode': 'imap_inbox', 'limit': _val(chat_input.get('limit')) or 20})

    if msg.startswith('view sent:'):
        return _routed({'mode': 'sent_emails', 'limit': _val(chat_input.get('limit')) or 20})

    if msg.startswith('search email:'):
        query = _val(chat_input.get('query')) or raw[len('search email:'):].strip()
        return _routed({'mode': 'imap_search', 'query': query, 'limit': 20})

    if msg.startswith('check event inbox:'):
        return _routed({'mode': 'event_inbox'})

    if msg.startswith('list email templates:'):
        return _routed({'mode': 'list_templates'})

    if msg.startswith('send welcome email:'):
        entity_id = _val(chat_input.get('entityId')) or _val(chat_input.get('leadId'))
        entity_type = _val(chat_input.get('entityType')) or 'lead'
        return _routed({
            'mode':         'send_template',
            'templateType': 'welcome',
            'entityType':   entity_type,
            'entityId':     entity_id,
        })

    if msg.startswith('send invoice email:'):
        entity_id = _val(chat_input.get('entityId')) or _val(chat_input.get('accountId'))
        return _routed({
            'mode':         'send_template',
            'templateType': 'invoice',
            'entityType':   'account',
            'entityId':     entity_id,
        })

    if msg.startswith('agent status:'):
        return _routed({'mode': 'agent_status'})

    return _passthru(raw, chat_input)
