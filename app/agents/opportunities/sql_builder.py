"""SQL Query Builder for sp_opportunities — Python conversion of n8n Build SQL Query node.

Key design:
  - Named-parameter style: only provided params are included.
  - Explicit PostgreSQL type casts: ::TEXT, ::UUID, ::DATE, ::INT, ::NUMERIC, ::JSONB.
  - AI Agent emits snake_case keys (not camelCase) — no alias mapping needed.
  - ROUTING_ONLY_PARAMS are stripped before reaching the SP.
  - Returns `SELECT sp_opportunities(...) AS result;`

Supported modes:
  list, get, create, update, delete
  add_product, update_product, remove_product
  pipeline, forecast
  search_accounts, search_products, search_opportunities
  get_owners
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_PARAMS = {
    # core
    'mode',
    'opportunity_id', 'account_id', 'contact_id',
    'name', 'amount', 'stage', 'probability', 'close_date',
    'description', 'lead_source', 'owner_id', 'status',
    # product-related
    'product_id', 'quantity', 'selling_price', 'discount', 'opp_product_id',
    # audit / metadata
    'payload', 'created_by', 'updated_by',
    # list filters
    'page_size', 'page_number', 'search', 'date_from', 'date_to',
    'min_probability', 'max_probability',
}

# Routing-only keys — stripped before the SP call
ROUTING_ONLY_PARAMS = {
    'bypassAgent', 'sessionId', 'currentMessage',
    'chatInput', 'chatHistory', 'originalBody',
}

REQUIRED_BY_MODE: Dict[str, list] = {
    'list':               [],
    'get':                ['opportunity_id'],
    'create':             ['account_id', 'name'],
    'update':             ['opportunity_id'],
    'change_stage':       ['opportunity_id', 'stage'],
    'close_won':          ['opportunity_id'],
    'close_lost':         ['opportunity_id'],
    'delete':             ['opportunity_id'],
    'add_product':        ['opportunity_id', 'product_id'],
    'update_product':     ['opp_product_id'],
    'remove_product':     ['opp_product_id'],
    'pipeline':           [],
    'forecast':           [],
    'search_accounts':    [],
    'search_products':    [],
    'search_opportunities': [],
    'get_owners':         [],
}

UUID_FIELDS = {
    'opportunity_id', 'account_id', 'contact_id', 'owner_id',
    'product_id', 'opp_product_id', 'created_by', 'updated_by',
}
DATE_FIELDS    = {'close_date', 'date_from', 'date_to'}
INTEGER_FIELDS = {'probability', 'page_size', 'page_number', 'min_probability', 'max_probability'}
NUMERIC_FIELDS = {'amount', 'quantity', 'selling_price', 'discount'}
JSONB_FIELDS   = {'payload'}
TEXT_FIELDS    = {'mode', 'name', 'stage', 'description', 'lead_source', 'status', 'search'}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    return s.replace("'", "''")


def _serialize(key: str, value: Any) -> str:
    """Serialize a parameter value with appropriate PostgreSQL type cast."""
    if value is None:
        return 'NULL'

    # JSONB
    if key in JSONB_FIELDS:
        if isinstance(value, (dict, list)):
            return f"'{_esc(json.dumps(value))}'::JSONB"
        return 'NULL'

    # UUID
    if key in UUID_FIELDS:
        s = str(value).strip()
        return f"'{_esc(s)}'::UUID" if s else 'NULL'

    # DATE
    if key in DATE_FIELDS:
        if isinstance(value, (date, datetime)):
            iso = value.strftime('%Y-%m-%d')
            return f"'{iso}'::DATE"
        if isinstance(value, str) and value.strip():
            return f"'{_esc(value.strip())}'::DATE"
        return 'NULL'

    # INTEGER
    if key in INTEGER_FIELDS:
        try:
            n = int(round(float(value)))
            return f"{n}::INT"
        except (TypeError, ValueError):
            return 'NULL'

    # NUMERIC
    if key in NUMERIC_FIELDS:
        try:
            n = float(value)
            if math.isfinite(n):
                return f"{n}::NUMERIC"
        except (TypeError, ValueError):
            pass
        return 'NULL'

    # TEXT (explicit)
    if key in TEXT_FIELDS:
        return f"'{_esc(str(value))}'::TEXT"

    # Fallback
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return f"{value}::NUMERIC" if math.isfinite(float(value)) else 'NULL'
    return f"'{_esc(str(value))}'::TEXT"


def _to_pg_param(key: str) -> str:
    return f'p_{key}'


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate(params: dict) -> list:
    errors = []
    mode = str(params.get('mode') or '').lower().strip()

    if not mode:
        errors.append("Parameter 'mode' is required")
        return errors

    if mode not in REQUIRED_BY_MODE:
        errors.append(f"Invalid mode: '{mode}'. Allowed: {', '.join(sorted(REQUIRED_BY_MODE))}")
        return errors

    for req in REQUIRED_BY_MODE[mode]:
        v = params.get(req)
        if v is None or (isinstance(v, str) and not v.strip()):
            errors.append(f"Required parameter missing for mode '{mode}': '{req}'")

    # Range checks
    for field in ('page_size',):
        if field in params and params[field] is not None:
            try:
                n = int(params[field])
                if n < 1 or n > 200:
                    errors.append('page_size must be between 1 and 200')
            except (TypeError, ValueError):
                errors.append('page_size must be an integer')

    for field in ('probability', 'min_probability', 'max_probability'):
        if field in params and params[field] is not None:
            try:
                n = int(params[field])
                if n < 0 or n > 100:
                    errors.append(f'{field} must be between 0 and 100')
            except (TypeError, ValueError):
                errors.append(f'{field} must be an integer')

    if 'amount' in params and params['amount'] is not None:
        try:
            n = float(params['amount'])
            if n < 0:
                errors.append('amount must be non-negative')
        except (TypeError, ValueError):
            errors.append('amount must be a number')

    if 'discount' in params and params['discount'] is not None:
        try:
            n = float(params['discount'])
            if n < 0 or n > 100:
                errors.append('discount must be between 0 and 100')
        except (TypeError, ValueError):
            errors.append('discount must be a number')

    return errors


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_opportunities_query(params: Dict[str, Any]) -> Tuple[str, Dict]:
    """
    Build `SELECT sp_opportunities(...) AS result;` from a params dict.

    Returns
    -------
    (sql, debug_info)

    Raises
    ------
    ValueError : on validation failure (mirrors n8n strict=False / shouldCallAPI=False path).
    """
    # Strip routing-only keys
    clean: dict = {
        k: v for k, v in params.items()
        if k not in ROUTING_ONLY_PARAMS
    }

    # Warn about unrecognised keys (don't block — mirrors collectAllErrors=True)
    unknown = [k for k in clean if k not in ALLOWED_PARAMS]
    for u in unknown:
        logger.warning(f"Unknown parameter ignored: '{u}'")
        del clean[u]

    mode = str(clean.get('mode') or '').lower().strip()
    logger.info(f"Building sp_opportunities query for mode='{mode}'")

    errors = _validate(clean)
    if errors:
        msg = "Validation failed for sp_opportunities:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    # Build named parameter list — skip None values
    named = []
    for key, value in clean.items():
        if key not in ALLOWED_PARAMS:
            continue
        if value is None:
            continue
        pg_key = _to_pg_param(key)
        pg_val = _serialize(key, value)
        if pg_val != 'NULL':
            named.append(f"{pg_key} := {pg_val}")

    param_list = ', '.join(named)
    sql = f"SELECT sp_opportunities({param_list}) AS result;"

    debug_info = {
        'mode': mode,
        'param_count': len(named),
        'params_used': [n.split(' := ')[0] for n in named],
    }

    logger.info(f"Built sp_opportunities query — {len(named)} params")
    logger.debug(f"SQL: {sql[:400]}")
    return sql, debug_info
