"""Opportunity Pre-Router v3.1 — Python conversion of n8n 'Code in JavaScript' node.

PRIMARY RULE: Every request with a known mode or recognisable natural-language
pattern is routed DIRECTLY to the SQL builder (router_action=True).
The AI Agent is called ONLY when no deterministic path exists.

SUPPORTED DIRECT MODES (always bypass AI):
  list, get, create, update, delete
  add_product, update_product, remove_product
  pipeline, forecast
  search_accounts, search_products        ← typeahead modes
  search_opportunities                    ← typeahead mode (v3)
  get_owners                              ← owner dropdown (v3.1)

NL COMMAND PATTERNS (v3):
  show_details:<UUID>       → { mode: 'get',    opportunity_id: UUID }
  update_opportunity:<UUID> → { mode: 'get',    opportunity_id: UUID }
  pipeline / sales pipeline → { mode: 'pipeline' }
  forecast                  → { mode: 'forecast' }
  list/show/display ... opportunities → { mode: 'list', ... }
  search/find ... opportunities       → { mode: 'list', search: ... }

ROUTING DECISION:
  router_action=True  → skip AI, send directly to SQL builder
  router_action=False → send to AI Agent
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All modes the SP can handle directly
# ---------------------------------------------------------------------------
DIRECT_MODES = {
    'list', 'get', 'create', 'update', 'delete',
    'add_product', 'update_product', 'remove_product',
    'pipeline', 'forecast',
    'search_accounts', 'search_products',
    'search_opportunities',
    'get_owners',
}

# SP parameter keys (snake_case, no p_ prefix).
# Anything NOT in this set is routing metadata and must be stripped.
SP_PARAMS = {
    'mode',
    'opportunity_id', 'account_id', 'contact_id',
    'name', 'amount', 'stage', 'probability', 'close_date',
    'description', 'lead_source', 'owner_id', 'status',
    'product_id', 'quantity', 'selling_price', 'discount', 'opp_product_id',
    'payload', 'created_by', 'updated_by',
    'page_size', 'page_number', 'search', 'date_from', 'date_to',
    'min_probability', 'max_probability',
}

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)

STAGE_MAP = {
    'prospecting':   re.compile(r'\bprospecting\b', re.IGNORECASE),
    'qualification': re.compile(r'\bqualification\b', re.IGNORECASE),
    'proposal':      re.compile(r'\bproposal\b', re.IGNORECASE),
    'negotiation':   re.compile(r'\bnegotiation\b', re.IGNORECASE),
    'closed_won':    re.compile(r'\bclosed.?won\b', re.IGNORECASE),
    'closed_lost':   re.compile(r'\bclosed.?lost\b', re.IGNORECASE),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_sp_params(obj: dict) -> dict:
    """Keep only keys recognised by sp_opportunities; drop routing metadata."""
    return {
        k: v for k, v in obj.items()
        if k in SP_PARAMS and v is not None and v != ''
    }


def _routed(params: dict) -> dict:
    logger.info(f"→ ROUTED: mode={params.get('mode')}")
    return {'router_action': True, 'params': params}


def _passthru(message: str) -> dict:
    logger.info(f"→ PASSTHRU: AI Agent  msg={message[:80]!r}")
    return {'router_action': False}


# ---------------------------------------------------------------------------
# Natural-language trigger patterns
# Order matters — first match wins.
# ---------------------------------------------------------------------------

def _match_nl(message: str) -> Optional[dict]:
    """
    Test NL trigger patterns against message.
    Returns params dict if matched, else None.
    """
    raw = message.strip()
    msg = raw.lower()

    # show_details:<UUID>
    m = re.match(r'^show_details:([0-9a-f-]{36})$', raw, re.IGNORECASE)
    if m:
        return {'mode': 'get', 'opportunity_id': m.group(1)}

    # update_opportunity:<UUID> — pre-load form (fetch details, don't update yet)
    m = re.match(r'^update_opportunity:([0-9a-f-]{36})$', raw, re.IGNORECASE)
    if m:
        return {'mode': 'get', 'opportunity_id': m.group(1)}

    # Pipeline
    if re.search(r'\b(pipeline|sales pipeline)\b', msg):
        return {'mode': 'pipeline'}

    # Forecast
    if re.search(r'\bforecast\b', msg):
        return {'mode': 'forecast'}

    # List opportunities (with optional stage filter)
    if re.search(r'\b(list|show|display|get)\b.*\bopportunit', msg):
        params: dict = {'mode': 'list', 'page_size': 50, 'page_number': 1}
        for stage, pattern in STAGE_MAP.items():
            if pattern.search(msg):
                params['stage'] = stage
                break
        ps = re.search(r'\bpage.?size\s+(\d+)\b', msg)
        if ps:
            params['page_size'] = int(ps.group(1))
        pg = re.search(r'\bpage\s+(\d+)\b', msg)
        if pg:
            params['page_number'] = int(pg.group(1))
        return params

    # Search / find opportunities
    if re.search(r'\b(search|find)\b.*\bopportunit', msg):
        params = {'mode': 'list', 'page_size': 50, 'page_number': 1}
        nm = re.search(r"(?:named?|called?)\s+[\"']?([^\"']+?)[\"']?(?:\s|$)", msg, re.IGNORECASE)
        if nm:
            params['search'] = nm.group(1).strip()
        return params

    return None


# ============================================================================
# MAIN ROUTER
# ============================================================================

def route_request(body: dict, chat_input: dict, session_id: str) -> dict:
    """
    Inspect the request and return a routing decision.

    Routed:   { 'router_action': True,  'params': { 'mode': ..., ... } }
    Passthru: { 'router_action': False }
    """
    logger.info('=== Opportunity Pre-Router v3.1 ===')

    # ── CASE 1: Structured body with a known mode ──────────────────────────
    # HTML forms and programmatic callers send { mode: 'create', ... }
    # directly in the request body.
    body_mode = str(body.get('mode') or '').lower().strip()
    if body_mode and body_mode in DIRECT_MODES:
        params = _extract_sp_params(body)
        params['mode'] = body_mode
        logger.info(f"CASE 1 – direct body mode: {body_mode}")
        return _routed(params)

    # ── CASE 2: Natural-language message matching a known pattern ──────────
    nl_message = (chat_input.get('message') or '').strip()

    # Supplement with legacy structured fields
    if chat_input.get('city'):        nl_message += f", city {chat_input['city']}"
    if chat_input.get('pageSize'):    nl_message += f", page size {chat_input['pageSize']}"
    if chat_input.get('pageNumber'):  nl_message += f", page number {chat_input['pageNumber']}"
    if chat_input.get('customerId'):  nl_message += f", customer ID {chat_input['customerId']}"

    if nl_message:
        matched = _match_nl(nl_message)
        if matched is not None:
            logger.info(f"CASE 2 – NL pattern matched: mode={matched.get('mode')}")
            return _routed(matched)

    # ── CASE 3: Fallback — unknown NL → AI Agent ───────────────────────────
    # Generate a descriptive message for webhook modes lacking chatInput
    if not nl_message:
        bm = body.get('mode', '')
        if bm == 'add_product':
            nl_message = (
                f"Add product {body.get('product_id','?')} to opportunity "
                f"{body.get('opportunity_id','?')} qty {body.get('quantity',1)} "
                f"disc {body.get('discount',0)} price {body.get('selling_price','default')}"
            )
        elif bm == 'update_product':
            nl_message = (
                f"Update product line {body.get('opp_product_id','?')} "
                f"qty {body.get('quantity','?')} disc {body.get('discount','?')} "
                f"price {body.get('selling_price','?')}"
            )
        else:
            import json
            nl_message = json.dumps(body)

    logger.info("CASE 3 – passthru to AI Agent")
    return _passthru(nl_message)
