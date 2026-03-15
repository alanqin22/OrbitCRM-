"""SQL Query Builder for sp_orders v4.0.

CHANGELOG v4.0
  - get_category, get_product added to VALID_MODES (sp_orders v5.4).
  - context and direct_query stripped as routing-only params before validation.
  - enrichParamsFromMessage() fallback for create mode missing fields.
  - UUID sanitation strips trailing garbage from markdown-rendered cells.

v3.9  direct_query context stripping guard.
v3.8  ROUTING_ONLY_PARAMS set (context, direct_query).
v3.7  enrichParamsFromMessage() — recover productId/productPricingId/orderDate.
v3.5  create mode required-field hardening: productId, productPricingId, orderDate.
v3.4  batch_update action; payload JSONB param.
v3.3  Date normalisation — strip time portion from ISO datetime strings.
v3.2  Ready, Invoiced added to VALID_STATUSES.
v3.1  contact_search, get_pricing; contactId param.
v3.0  orderItemId, createdBy, updatedBy; account_search, list_employees.

Key notes:
  - ROUTING_ONLY_PARAMS ('context') are stripped before validation.
  - payload is serialised as ::jsonb.
  - orderDate/startDate/endDate: ISO datetime strings auto-stripped to YYYY-MM-DD.
  - Result alias: 'result'  (SELECT sp_orders(...) AS result;)
"""

from __future__ import annotations

import json
import re
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Routing-only params — never forwarded to the SP
ROUTING_ONLY_PARAMS = {'context', 'direct_query'}

VALID_PARAMS = {
    'mode', 'action',
    'orderId', 'orderNumber',
    'accountId', 'contactId',
    'status', 'orderDate',
    'orderItemId',
    'productId', 'quantity',
    'productPricingId', 'priceType',
    'payload',
    'createdBy', 'updatedBy',
    'pageSize', 'pageNumber',
    'search', 'startDate', 'endDate', 'year',
    'categoryId',
    'sortField', 'sortOrder',
    'forceHardDelete', 'includeDeleted',
}

VALID_MODES = {
    'list', 'get_detail', 'create', 'update', 'delete',
    'account_summary', 'category_summary', 'sales_summary',
    'account_search', 'list_employees', 'contact_search',
    'get_pricing', 'get_category', 'get_product',
}

VALID_ACTIONS = {
    'update_header', 'add_item', 'remove_item', 'change_status',
    'soft_delete', 'restore', 'hard_delete', 'batch_update',
}

VALID_STATUSES = {
    'Pending', 'Processing', 'Ready', 'Invoiced',
    'Shipped', 'Delivered', 'Completed', 'Cancelled', 'Refunded',
}

VALID_PRICE_TYPES = {'Retail', 'Promo', 'Wholesale'}

REQUIRED_BY_MODE: Dict[str, List[str]] = {
    'list':             [],
    'get_detail':       [],   # orderId OR orderNumber checked separately
    'create':           ['accountId', 'productId', 'productPricingId', 'orderDate'],
    'update':           [],   # per-action rules below
    'delete':           [],   # orderId OR orderNumber checked separately
    'account_summary':  [],
    'category_summary': [],
    'sales_summary':    [],
    'account_search':   ['search'],
    'list_employees':   [],
    'contact_search':   [],   # search or accountId, both optional
    'get_pricing':      ['productId'],
    'get_category':     [],
    'get_product':      [],
}

DATE_PARAMS = ('orderDate', 'startDate', 'endDate')
JSONB_PARAMS = {'payload'}
DATE_RE  = re.compile(r'^\d{4}-\d{2}-\d{2}$')
UUID_RE  = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v.strip() == '')


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _to_pg(key: str) -> str:
    """camelCase → p_snake_case."""
    s = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', key)
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s).lower()
    return f'p_{s}'


def _serialize(key: str, value: Any) -> str:
    if value is None:
        return 'NULL'
    if key in JSONB_PARAMS:
        return f"'{_esc(json.dumps(value))}'::jsonb"
    if isinstance(value, (datetime, date)):
        d = value.date() if isinstance(value, datetime) else value
        return f"'{d.isoformat()}'"
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return f"'{_esc(value)}'"
    return f"'{_esc(str(value))}'"


def _strip_date_time(v: str) -> str:
    """'2026-02-10T19:00:00Z' → '2026-02-10'"""
    return v.split('T')[0] if 'T' in v else v


# ---------------------------------------------------------------------------
# Fallback enrichment (v3.7)
# For 'create' mode, recover fields the AI Agent may have missed from the
# raw chat message. Never overwrites params already set.
# ---------------------------------------------------------------------------

def _enrich_from_message(params: dict, message: str) -> None:
    if not message or params.get('mode', '').lower() != 'create':
        return
    uuid_pat = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    if not params.get('productId'):
        m = re.search(rf'\bproduct\s+({uuid_pat})', message, re.IGNORECASE)
        if m:
            params['productId'] = m.group(1)
    if not params.get('productPricingId'):
        m = re.search(rf'\bpricingId=({uuid_pat})', message, re.IGNORECASE)
        if m:
            params['productPricingId'] = m.group(1)
    if not params.get('orderDate'):
        m = re.search(r'\borderDate=([^\s]+)', message, re.IGNORECASE)
        if m:
            params['orderDate'] = _strip_date_time(m.group(1))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(params: dict) -> List[str]:
    errors: List[str] = []
    mode = str(params.get('mode') or '').lower().strip()

    if not mode:
        errors.append("Parameter 'mode' is required")
        return errors
    if mode not in VALID_MODES:
        errors.append(f"Invalid mode: '{mode}'. Allowed: {', '.join(sorted(VALID_MODES))}")
        return errors

    # Base required fields
    for req in REQUIRED_BY_MODE.get(mode, []):
        if not _has(params.get(req)):
            errors.append(f"Required parameter missing for mode '{mode}': '{req}'")

    # get_detail / delete: orderId OR orderNumber
    if mode in ('get_detail', 'delete'):
        if not params.get('orderId') and not params.get('orderNumber'):
            errors.append(f"'{mode}' requires either 'orderId' or 'orderNumber'")

    # update: action required + per-action rules
    if mode == 'update':
        action = params.get('action')
        if not action:
            errors.append("update mode requires 'action'")
        else:
            if action not in VALID_ACTIONS:
                errors.append(f"Invalid action: '{action}'. Allowed: {', '.join(sorted(VALID_ACTIONS))}")
            if not params.get('orderId') and not params.get('orderNumber'):
                errors.append(f"update/{action} requires either 'orderId' or 'orderNumber'")
            if action == 'add_item' and not params.get('productId'):
                errors.append("update/add_item requires 'productId'")
            if action == 'remove_item' and not params.get('orderItemId'):
                errors.append("update/remove_item requires 'orderItemId'")
            if action == 'change_status' and not params.get('status'):
                errors.append("update/change_status requires 'status'")
            if action == 'hard_delete' and params.get('forceHardDelete') is not True:
                errors.append("update/hard_delete requires 'forceHardDelete': true")
            if action == 'batch_update':
                if params.get('payload') is None:
                    errors.append("update/batch_update requires 'payload' (object with keys: header, items_to_remove, items_to_add)")
                elif not isinstance(params['payload'], dict) or isinstance(params['payload'], list):
                    errors.append("update/batch_update 'payload' must be a plain object (JSONB)")

    # Type checks
    for int_param, lo, hi in [('pageSize', 1, 1000), ('pageNumber', 1, None)]:
        v = params.get(int_param)
        if v is not None:
            if not isinstance(v, int) or (lo and v < lo) or (hi and v > hi):
                errors.append(f"'{int_param}' must be an integer{' >= ' + str(lo) if lo else ''}{' <= ' + str(hi) if hi else ''}")

    if params.get('quantity') is not None:
        q = params['quantity']
        if not isinstance(q, int) or q <= 0:
            errors.append("'quantity' must be a positive integer")

    if params.get('year') is not None:
        yr = params['year']
        if not isinstance(yr, int) or not (1900 <= yr <= 3000):
            errors.append("'year' must be an integer between 1900 and 3000")

    if params.get('includeDeleted') is not None and not isinstance(params['includeDeleted'], bool):
        errors.append("'includeDeleted' must be a boolean")

    if params.get('forceHardDelete') is not None and not isinstance(params['forceHardDelete'], bool):
        errors.append("'forceHardDelete' must be a boolean")

    status = params.get('status')
    if status and status not in VALID_STATUSES:
        errors.append(f"Invalid status: '{status}'. Allowed: {', '.join(sorted(VALID_STATUSES))}")

    sort_order = params.get('sortOrder')
    if sort_order and sort_order.upper() not in ('ASC', 'DESC'):
        errors.append("'sortOrder' must be 'ASC' or 'DESC'")

    return errors


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_orders_query(params: Dict[str, Any], raw_message: str = '') -> Tuple[str, dict]:
    """
    Build `SELECT sp_orders(...) AS result;` from params dict.

    Returns (sql, debug_info). Raises ValueError on validation failure.

    Key behaviours:
      - ROUTING_ONLY_PARAMS (context, direct_query) stripped before validation.
      - payload serialised as ::jsonb.
      - Date params: ISO datetime strings auto-stripped to YYYY-MM-DD.
      - UUID params sanitised (trailing garbage stripped).
      - For 'create' mode, missing productId/productPricingId/orderDate
        recovered from raw_message as a safety net.
    """
    # Strip routing-only fields
    for k in ROUTING_ONLY_PARAMS:
        params.pop(k, None)

    # UUID sanitisation
    uuid_keys = [
        'orderId', 'accountId', 'contactId', 'productId',
        'productPricingId', 'orderItemId', 'createdBy', 'updatedBy',
    ]
    for k in uuid_keys:
        if k in params and params[k] and isinstance(params[k], str):
            from .pre_router import _clean_uuid
            cleaned = _clean_uuid(params[k])
            if cleaned:
                params[k] = cleaned

    # Date normalisation — strip time portion
    for dp in DATE_PARAMS:
        v = params.get(dp)
        if isinstance(v, str) and 'T' in v:
            params[dp] = _strip_date_time(v)

    # Fallback enrichment for create mode
    _enrich_from_message(params, raw_message)

    # Warn on unknown params
    for k in list(params.keys()):
        if k not in VALID_PARAMS:
            logger.warning(f"Unknown parameter stripped: '{k}'")
            params.pop(k)

    errors = _validate(params)
    if errors:
        msg = "Validation failed for sp_orders:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    mode = params.get('mode', 'unknown')
    logger.info(f"Building sp_orders query — mode={mode} action={params.get('action', '')}")

    # Build named params
    named: List[str] = []
    for key, value in params.items():
        if key not in VALID_PARAMS:
            continue
        named.append(f"{_to_pg(key)} := {_serialize(key, value)}")

    sql = f"SELECT sp_orders({', '.join(named)}) AS result;"

    debug_info = {
        'mode':        mode,
        'action':      params.get('action'),
        'param_count': len(named),
        'params_used': [n.split(' := ')[0] for n in named],
    }

    logger.info(f"Built sp_orders query — {len(named)} params")
    logger.debug(f"SQL: {sql[:400]}")
    return sql, debug_info
