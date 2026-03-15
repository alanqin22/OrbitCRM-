"""SQL Query Builder for sp_contacts — aligned with n8n Build SQL Query v2.1.

v2.1 FIXES (March 2026):
  - tokenExpiresHours validation uses != null (catches both null AND undefined).
    Previously used !== undefined, so null passed the guard and failed isInteger check.
  - Query builder loop SKIPS null/undefined values instead of emitting NULL.
    Prevents optional SP params with DEFAULTs (e.g. tokenExpiresHours) being overridden.
  - Same null-guard pattern applied to pageSize, pageNumber, includeDeleted, deletedOnly.

Key design: only non-None parameters are emitted in the SQL call. sp_contacts
has PostgreSQL DEFAULT values for all optional params; emitting NULL would
override them and break SP behaviour.
"""

import json
import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

VALID_MODES = {
    'list', 'get_details', 'create', 'update',
    'send_verification', 'verify_email',
    'duplicates', 'merge',
    'archive', 'restore',
    'activities', 'summary',
}

# Mode alias: legacy 'get' → canonical 'get_details'
MODE_ALIASES = {'get': 'get_details'}

VALID_PARAMS = {
    'mode', 'operation',
    'contactId', 'accountId',
    'firstName', 'lastName',
    'email', 'phone',
    'role', 'ownerId', 'status',
    'payload', 'createdBy', 'updatedBy',
    'token', 'tokenExpiresHours', 'verificationIp',
    'pageSize', 'pageNumber',
    'search', 'includeDeleted', 'deletedOnly',
    'billingAddress', 'shippingAddress',
    'dateFrom', 'dateTo',
}

JSONB_PARAMS = {'payload', 'billingAddress', 'shippingAddress'}

# Modes that require at least one contact identifier
_IDENTIFIER_MODES = {'get_details', 'activities', 'send_verification', 'verify_email'}

# snake_case → camelCase normalisation for legacy payloads
_SNAKE_TO_CAMEL = {
    'contact_id':          'contactId',
    'account_id':          'accountId',
    'first_name':          'firstName',
    'last_name':           'lastName',
    'owner_id':            'ownerId',
    'created_by':          'createdBy',
    'updated_by':          'updatedBy',
    'token_expires_hours': 'tokenExpiresHours',
    'verification_ip':     'verificationIp',
    'page_size':           'pageSize',
    'page_number':         'pageNumber',
    'include_deleted':     'includeDeleted',
    'deleted_only':        'deletedOnly',
    'date_from':           'dateFrom',
    'date_to':             'dateTo',
    'billing_address':     'billingAddress',
    'shipping_address':    'shippingAddress',
}

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


# ============================================================================
# HELPERS
# ============================================================================

def _is_uuid(v: Any) -> bool:
    return isinstance(v, str) and bool(UUID_PATTERN.match(v))


def _has_value(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v.strip() == '')


def _to_pg_param(camel: str) -> str:
    """Convert camelCase to p_snake_case PostgreSQL parameter name."""
    snake = re.sub(r'([A-Z])', lambda m: f'_{m.group(1).lower()}', camel)
    return f'p_{snake}'


def _fmt(value: Any, key: str) -> Optional[str]:
    """
    Format a Python value as a SQL literal.
    Returns None if the value should be skipped (null/undefined).
    Mirrors v2.1 fix: skip null/undefined instead of emitting NULL.
    """
    # v2.1 fix: skip None entirely — do NOT emit NULL for optional params
    if value is None:
        return None

    if key in JSONB_PARAMS:
        if value and isinstance(value, dict):
            escaped = json.dumps(value).replace("'", "''")
            return f"'{escaped}'::jsonb"
        return None     # skip empty JSONB

    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'

    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"

    if isinstance(value, (int, float)):
        return str(value)

    # Fallback: stringify
    return f"'{str(value).replace(chr(39), chr(39)*2)}'"


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_contacts_query(params: Dict[str, Any]) -> Tuple[str, Dict]:
    """
    Validate params and build a SELECT sp_contacts(...) SQL string.

    Returns
    -------
    (sql, debug_info)

    Raises
    ------
    ValueError : Validation failure — message lists all errors.
    """
    # ── snake_case → camelCase normalisation  ────────────────────────────────
    normalised: Dict[str, Any] = {}
    for key, value in params.items():
        camel = _SNAKE_TO_CAMEL.get(key, key)
        if camel not in normalised:
            normalised[camel] = value
    params = normalised

    # ── Mode alias  ──────────────────────────────────────────────────────────
    if 'mode' in params and params['mode'] in MODE_ALIASES:
        params['mode'] = MODE_ALIASES[params['mode']]

    errors: list = []
    warnings: list = []

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
    REQUIRED_BY_MODE = {
        'create':  ['firstName', 'lastName', 'email'],
        'update':  ['contactId'],
        'archive': ['contactId'],
        'restore': ['contactId'],
        'merge':   ['operation'],
        'verify_email': ['token'],
    }

    if mode and mode in REQUIRED_BY_MODE:
        for req in REQUIRED_BY_MODE[mode]:
            if not _has_value(params.get(req)):
                errors.append(f"Required parameter missing for mode '{mode}': '{req}'")

    # ── Unified identifier check  ─────────────────────────────────────────────
    if mode in _IDENTIFIER_MODES:
        has_id = (
            _has_value(params.get('contactId')) or
            _has_value(params.get('email')) or
            _has_value(params.get('phone')) or
            (_has_value(params.get('firstName')) and _has_value(params.get('lastName')))
        )
        if not has_id:
            errors.append(
                f"For mode '{mode}', provide at least one identifier: "
                f"contactId, email, phone, or (firstName + lastName)"
            )

        if params.get('contactId') and not _is_uuid(params['contactId']):
            errors.append(f"Invalid UUID format for 'contactId' in mode '{mode}'")

    # ── Merge validation  ─────────────────────────────────────────────────────
    if mode == 'merge':
        op = str(params.get('operation') or '').lower().strip()
        if op not in ('by_email', 'by_phone'):
            errors.append("For mode 'merge', operation must be 'by_email' or 'by_phone'")
        if op == 'by_email' and not _has_value(params.get('email')):
            errors.append("For 'by_email' merge, 'email' is required")
        if op == 'by_phone' and not _has_value(params.get('phone')):
            errors.append("For 'by_phone' merge, 'phone' is required")

    # ── Type / range validation  ──────────────────────────────────────────────

    # v2.1 fix: use != None (catches both None and 0 correctly with isdigit check)
    page_size = params.get('pageSize')
    if page_size is not None:
        try:
            ps = int(page_size)
            if ps < 1 or ps > 200:
                errors.append('pageSize must be integer between 1 and 200')
        except (TypeError, ValueError):
            errors.append('pageSize must be integer between 1 and 200')

    page_number = params.get('pageNumber')
    if page_number is not None:
        try:
            pn = int(page_number)
            if pn < 1:
                errors.append('pageNumber must be integer >= 1')
        except (TypeError, ValueError):
            errors.append('pageNumber must be integer >= 1')

    # v2.1 fix: tokenExpiresHours uses != None (previously !== undefined allowed None through)
    token_hours = params.get('tokenExpiresHours')
    if token_hours is not None:
        try:
            th = int(token_hours)
            if th < 1 or th > 168:
                errors.append('tokenExpiresHours must be integer between 1 and 168')
        except (TypeError, ValueError):
            errors.append('tokenExpiresHours must be integer between 1 and 168')

    if params.get('includeDeleted') is not None and not isinstance(params['includeDeleted'], bool):
        errors.append('includeDeleted must be boolean')

    if params.get('deletedOnly') is not None and not isinstance(params['deletedOnly'], bool):
        errors.append('deletedOnly must be boolean')

    if params.get('email') and not EMAIL_PATTERN.match(str(params['email'])):
        errors.append('Invalid email format')

    if params.get('phone'):
        digits = re.sub(r'\D', '', str(params['phone']))
        if len(digits) < 7:
            warnings.append('Phone number appears too short - may not be valid')

    if params.get('dateFrom'):
        try:
            datetime.fromisoformat(str(params['dateFrom']))
        except ValueError:
            errors.append('Invalid dateFrom format (expected YYYY-MM-DD)')

    if params.get('dateTo'):
        try:
            datetime.fromisoformat(str(params['dateTo']))
        except ValueError:
            errors.append('Invalid dateTo format (expected YYYY-MM-DD)')

    if errors:
        raise ValueError('; '.join(errors))

    # ── Build SQL  ───────────────────────────────────────────────────────────
    named_parts = []
    used_params = []

    for key, value in params.items():
        if key not in VALID_PARAMS:
            continue

        # v2.1 fix: skip None/undefined entirely — do NOT emit NULL
        if value is None:
            continue

        formatted = _fmt(value, key)
        if formatted is None:
            continue

        pg_param = _to_pg_param(key)
        named_parts.append(f"{pg_param} := {formatted}")
        used_params.append(pg_param)

    sql = f"SELECT sp_contacts({', '.join(named_parts)}) AS result;"

    logger.info(f"Built sp_contacts query for mode '{mode}' (v2.1)")
    logger.debug(f"SQL: {sql[:300]}")

    debug_info = {
        'paramCount':  len(named_parts),
        'usedParams':  used_params,
        'warnings':    warnings,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
    }

    return sql, debug_info
