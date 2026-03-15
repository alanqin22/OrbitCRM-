"""SQL Query Builder for sp_leads v2.3 — Python conversion of n8n Build SQL Query node.

Key design notes:
  - Parameters use camelCase (matching HTML chatInput fields).
  - camelCase keys are converted to p_snake_case automatically.
  - CRITICAL: null/None params are SKIPPED entirely — never serialised as the
    string 'null'. When the pre-router sends optional params as Python None,
    they must be dropped so the SP uses its own defaults (not the literal
    string 'null' which would break WHERE clauses and return 0 rows).
  - payload (JSONB): serialised as '{"reason":"..."}'::jsonb.
  - Boolean params: TRUE / FALSE (no quotes).
  - score: integer 0–100, no quotes.

CHANGELOG v2.3 (critical fix)
  - null params are now skipped entirely instead of being passed as the string
    'null'. The old path produced p_search := 'null' etc., which the SP
    received as a non-NULL string, breaking all WHERE logic and returning 0
    rows even when data existed. The AI Agent path was unaffected because it
    only forwarded params with real values.
v2.2 — list_employee mode added.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PARAMS = {
    'mode',
    'leadId',
    'operation',
    'firstName',
    'lastName',
    'company',
    'email',
    'phone',
    'addressLine1',
    'addressLine2',
    'city',
    'province',
    'postalCode',
    'country',
    'source',
    'status',
    'rating',
    'ownerId',
    'score',
    'campaignId',
    'payload',
    'createdBy',
    'updatedBy',
    'pageSize',
    'pageNumber',
    'search',
    'includeDeleted',
    'deletedOnly',
    # qualify alias (pre-router sends payload; AI Agent may send reason directly)
    'reason',
}

JSONB_PARAMS = {'payload'}

REQUIRED_BY_MODE: Dict[str, List[str]] = {
    'list':          [],
    'get':           [],          # validated separately: leadId OR email
    'create':        [],          # validated separately: firstName OR lastName
    'update':        ['leadId'],
    'qualify':       ['leadId'],
    'convert':       ['leadId'],
    'archive':       ['leadId'],
    'restore':       ['leadId'],
    'score':         ['leadId'],
    'duplicates':    [],
    'merge':         ['operation'],
    'pipeline':      [],
    'list_employee': [],
}

VALID_MODES = set(REQUIRED_BY_MODE.keys())

VALID_RATINGS  = {'hot', 'warm', 'cold'}
EMAIL_RE       = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_value(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v.strip() == '')


def _camel_to_snake(name: str) -> str:
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _to_pg_param(key: str) -> str:
    if key.startswith('p_'):
        return key
    return f'p_{_camel_to_snake(key)}'


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _serialize(key: str, value: Any) -> str:
    """Serialise a parameter value for SQL. Never called with None."""
    # JSONB
    if key in JSONB_PARAMS:
        if isinstance(value, (dict, list)):
            return f"'{_esc(json.dumps(value))}'::jsonb"
        return 'NULL'

    # datetime
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"

    # Boolean (must come before int — bool is a subclass of int in Python)
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'

    # String
    if isinstance(value, str):
        return f"'{_esc(value)}'"

    # Numeric
    return str(value)


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

    # Mode-specific required fields
    for req in REQUIRED_BY_MODE.get(mode, []):
        if not _has_value(params.get(req)):
            errors.append(f"Required parameter missing for mode '{mode}': '{req}'")

    # Special: get → leadId OR email
    if mode == 'get' and not _has_value(params.get('leadId')) and not _has_value(params.get('email')):
        errors.append("For mode 'get', either 'leadId' or 'email' is required")

    # Special: create → firstName OR lastName
    if mode == 'create' and not _has_value(params.get('firstName')) and not _has_value(params.get('lastName')):
        errors.append("For mode 'create', at least 'firstName' or 'lastName' is required")

    # pageSize
    if params.get('pageSize') is not None:
        try:
            ps = int(params['pageSize'])
            if ps < 1 or ps > 200:
                errors.append('pageSize must be between 1 and 200')
        except (TypeError, ValueError):
            errors.append('pageSize must be an integer')

    # pageNumber
    if params.get('pageNumber') is not None:
        try:
            pn = int(params['pageNumber'])
            if pn < 1:
                errors.append('pageNumber must be >= 1')
        except (TypeError, ValueError):
            errors.append('pageNumber must be an integer')

    # Boolean flags
    for flag in ('includeDeleted', 'deletedOnly'):
        if params.get(flag) is not None and not isinstance(params[flag], bool):
            errors.append(f"'{flag}' must be a boolean")

    # score
    if params.get('score') is not None:
        try:
            sc = int(params['score'])
            if sc < 0 or sc > 100:
                errors.append('score must be between 0 and 100')
        except (TypeError, ValueError):
            errors.append('score must be an integer')

    # rating
    if params.get('rating') and str(params['rating']).lower() not in VALID_RATINGS:
        errors.append(f"Invalid rating '{params['rating']}'. Allowed: {', '.join(sorted(VALID_RATINGS))}")

    # email
    if params.get('email') and not EMAIL_RE.match(str(params['email'])):
        errors.append('Invalid email format')

    return errors


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_leads_query(params: Dict[str, Any]) -> Tuple[str, dict]:
    """
    Build `SELECT sp_leads(...) AS result;` from a camelCase params dict.

    CRITICAL: None values are SKIPPED — never serialised as the string 'null'.
    Skipping lets the SP use its own parameter defaults, preserving all WHERE
    logic and returning the expected rows.

    Returns (sql, debug_info). Raises ValueError on validation failure.
    """
    # 1. Warn on unknown params, keep known ones only
    clean: Dict[str, Any] = {}
    for k, v in params.items():
        if k not in VALID_PARAMS:
            logger.warning(f"Unknown parameter ignored: '{k}'")
            continue
        clean[k] = v

    # 2. Handle 'reason' alias → wrap into payload (AI Agent path)
    if 'reason' in clean and 'payload' not in clean:
        reason = clean.pop('reason')
        if _has_value(reason):
            clean['payload'] = {'reason': reason}
        else:
            clean.pop('reason', None)
    else:
        clean.pop('reason', None)  # drop if payload already present

    mode = str(clean.get('mode') or '').lower().strip()
    logger.info(f"Building sp_leads query for mode='{mode}'")

    # 3. Validate
    errors = _validate(clean)
    if errors:
        msg = "Validation failed for sp_leads:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    # 4. Build named parameter list — SKIP None values entirely
    named: List[str] = []
    for key, value in clean.items():
        if key not in VALID_PARAMS:
            continue

        # ── CRITICAL: skip None/undefined — never pass as the string 'null' ──
        if value is None:
            continue

        pg_key = _to_pg_param(key)
        pg_val = _serialize(key, value)
        named.append(f"{pg_key} := {pg_val}")

    param_str = ', '.join(named)
    sql = f"SELECT sp_leads({param_str}) AS result;"

    debug_info = {
        'mode':        mode,
        'param_count': len(named),
        'params_used': [n.split(' := ')[0] for n in named],
    }

    logger.info(f"Built sp_leads query — {len(named)} params")
    logger.debug(f"SQL: {sql[:400]}")
    return sql, debug_info
