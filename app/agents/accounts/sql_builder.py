"""SQL Query Builder for sp_accounts — aligned with n8n Build SQL Query v2.8.

Key design: Only provided parameters are included in the call (unlike the
accounting module which sends all 34 params as NULLs). sp_accounts uses
PostgreSQL named-parameter notation and ignores unset params internally.

v2.8 changes vs v2.7:
  Trim whitespace from ALL string params before SQL quoting.
  Fixes: leading/trailing spaces in UUIDs causing "invalid input syntax for
  type uuid" errors (e.g. " aa9f8cfe-..." from direct SP calls).
"""

import json
import re
import logging
from typing import Any, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

VALID_MODES = {
    'list', 'get', 'create', 'update',
    'timeline', 'financials', 'duplicates',
    'merge', 'archive', 'restore', 'summary',
}

VALID_PARAMS = {
    'mode', 'operation', 'accountId', 'accountName',
    'type', 'industry', 'phone', 'email', 'website',
    'billingAddress', 'shippingAddress', 'ownerId', 'status',
    'payload', 'createdBy', 'updatedBy', 'pageSize', 'pageNumber',
    'search', 'includeDeleted', 'deletedOnly', 'dateFrom', 'dateTo',
}

# Modes that require at least one identifier (accountId / accountName / email / phone)
_NEEDS_IDENTIFIER = {'get', 'timeline', 'financials'}

# Fields that must be validated as UUIDs after trimming
_UUID_PARAMS = {'accountId', 'ownerId', 'createdBy', 'updatedBy'}

# Fields serialised as JSONB literals
_JSONB_PARAMS = {'billingAddress', 'shippingAddress', 'payload'}

# Keys injected by the pre-router / n8n that are NOT sp_accounts parameters
_ROUTING_ONLY = {
    'sessionId', 'chatInput', 'message', 'originalBody',
    'webhookUrl', 'executionMode', 'routerAction',
    'currentMessage', 'chatHistory',
}

# snake_case → camelCase normalisation map
# (pre-router v3.0 "account direct:" forwards chatInput fields verbatim)
_SNAKE_TO_CAMEL = {
    'account_id':       'accountId',
    'account_name':     'accountName',
    'owner_id':         'ownerId',
    'billing_address':  'billingAddress',
    'shipping_address': 'shippingAddress',
    'page_size':        'pageSize',
    'page_number':      'pageNumber',
    'include_deleted':  'includeDeleted',
    'deleted_only':     'deletedOnly',
    'date_from':        'dateFrom',
    'date_to':          'dateTo',
    'created_by':       'createdBy',
    'updated_by':       'updatedBy',
}

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


# ============================================================================
# HELPERS
# ============================================================================

def _to_pg_param(camel: str) -> str:
    """Convert camelCase key to p_snake_case PostgreSQL parameter name."""
    snake = re.sub(r'([A-Z])', lambda m: f'_{m.group(1).lower()}', camel)
    return f'p_{snake}'


def _fmt(value: Any, key: str) -> str:
    """Format a Python value as a SQL literal for a named parameter."""
    if key in _JSONB_PARAMS:
        if value and isinstance(value, dict):
            escaped = json.dumps(value).replace("'", "''")
            return f"'{escaped}'::jsonb"
        return 'NULL'

    if isinstance(value, str):
        trimmed = value.strip()
        escaped = trimmed.replace("'", "''")
        return f"'{escaped}'"

    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'

    if isinstance(value, (int, float)):
        return str(value)

    return 'NULL'


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_accounts_query(params: Dict[str, Any]) -> Tuple[str, Optional[Dict]]:
    """
    Validate params and build a SELECT sp_accounts(...) SQL string.

    Returns
    -------
    (sql, debug_info)
      sql        : Fully-formed SQL string ready for psycopg2 execution.
      debug_info : Dict with paramCount, usedParams, generatedAt (or None on error).

    Raises
    ------
    ValueError   : Validation failure — message lists all errors.
    """
    # ── Strip routing-only keys ──────────────────────────────────────────────
    params = {k: v for k, v in params.items() if k not in _ROUTING_ONLY}

    # ── Normalise snake_case → camelCase  ────────────────────────────────────
    normalised: Dict[str, Any] = {}
    for key, value in params.items():
        camel = _SNAKE_TO_CAMEL.get(key, key)
        if camel not in normalised:          # camelCase wins if both forms present
            normalised[camel] = value
    params = normalised

    errors = []
    warnings = []

    # ── Unknown parameter detection  ─────────────────────────────────────────
    for key in params:
        if key not in VALID_PARAMS:
            warnings.append(f"Ignored unknown parameter: {key}")

    # ── Mode validation  ─────────────────────────────────────────────────────
    raw_mode = params.get('mode')
    mode = str(raw_mode).lower().strip() if raw_mode else None

    if not mode:
        errors.append("Parameter 'mode' is required")
    elif mode not in VALID_MODES:
        errors.append(
            f"Invalid mode: '{mode}'. Allowed: {', '.join(sorted(VALID_MODES))}"
        )

    # ── Required fields by mode  ─────────────────────────────────────────────
    if mode == 'create':
        v = params.get('accountName')
        if not v or (isinstance(v, str) and not v.strip()):
            errors.append("Required parameter missing for mode 'create': 'accountName'")

    if mode in ('update', 'archive', 'restore'):
        if not params.get('accountId'):
            errors.append(f"Required parameter missing for mode '{mode}': 'accountId'")

    # ── Identifier check for get / timeline / financials  ────────────────────
    if mode in _NEEDS_IDENTIFIER:
        if not any(params.get(k) for k in ('accountId', 'accountName', 'email', 'phone')):
            errors.append(
                f"{mode} mode requires at least one identifier: "
                f"accountId, accountName, email, or phone"
            )

    # ── Merge validation  ─────────────────────────────────────────────────────
    if mode == 'merge':
        op = str(params.get('operation') or '').lower().strip()
        if op not in ('by_name_city', 'by_email', 'by_phone'):
            errors.append("For merge, operation must be: by_name_city, by_email, by_phone")
        else:
            if op == 'by_name_city' and (not params.get('accountName') or not params.get('billingAddress')):
                errors.append("For by_name_city merge, 'accountName' and 'billingAddress' are required")
            if op == 'by_email' and not params.get('email'):
                errors.append("For by_email merge, 'email' is required")
            if op == 'by_phone' and not params.get('phone'):
                errors.append("For by_phone merge, 'phone' is required")

    # ── Type / range validation  ──────────────────────────────────────────────
    if params.get('pageSize') is not None:
        ps = int(params['pageSize']) if str(params['pageSize']).isdigit() else -1
        if ps < 1 or ps > 200:
            errors.append('pageSize must be integer between 1 and 200')

    if params.get('pageNumber') is not None:
        pn = int(params['pageNumber']) if str(params['pageNumber']).isdigit() else -1
        if pn < 1:
            errors.append('pageNumber must be integer >= 1')

    if params.get('includeDeleted') is not None and not isinstance(params['includeDeleted'], bool):
        errors.append('includeDeleted must be boolean')

    if params.get('deletedOnly') is not None and not isinstance(params['deletedOnly'], bool):
        errors.append('deletedOnly must be boolean')

    if params.get('email') and not EMAIL_PATTERN.match(params['email']):
        errors.append('Invalid email format')

    if params.get('phone'):
        digits = re.sub(r'\D', '', str(params['phone']))
        if len(digits) < 7:
            warnings.append('Phone number appears too short')

    # ── UUID validation + in-place trim  ─────────────────────────────────────
    for key in _UUID_PARAMS:
        if params.get(key):
            trimmed = str(params[key]).strip()
            if not UUID_PATTERN.match(trimmed):
                errors.append(f"Parameter '{key}' is not a valid UUID: '{params[key]}'")
            else:
                params[key] = trimmed      # apply trim before SQL build

    if errors:
        raise ValueError('; '.join(errors))

    # ── Build SQL  ───────────────────────────────────────────────────────────
    named_parts = []
    used_params = []

    for key, value in params.items():
        if key not in VALID_PARAMS:
            continue                       # silently skip unknown params

        pg_param  = _to_pg_param(key)
        formatted = _fmt(value, key)

        if formatted == 'NULL' and key not in _JSONB_PARAMS:
            continue                       # omit NULL scalars (sp_accounts has defaults)

        named_parts.append(f"{pg_param} := {formatted}")
        used_params.append(pg_param)

    sql = f"SELECT sp_accounts({', '.join(named_parts)}) AS result;"

    logger.info(f"Built sp_accounts query for mode '{mode}' (v2.8)")
    logger.debug(f"SQL: {sql[:300]}")

    from datetime import datetime, timezone
    debug_info = {
        'paramCount':  len(named_parts),
        'usedParams':  used_params,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'warnings':    warnings,
    }

    return sql, debug_info
