"""SQL Query Builder for sp_activities v3.0 — Python conversion of n8n Build SQL Query node.

Key design notes:
  - Parameters use camelCase (matching HTML chatInput fields).
  - camelCase keys are converted to p_snake_case via toPgParam().
  - Special remaps: dueDate → p_due_at, completedAt → p_completed_at.
  - completedAt=None produces p_completed_at := NULL (explicit NULL for reopen).
  - No PostgreSQL type casts — the SP accepts plain quoted values.
  - ROUTING_ONLY_PARAMS stripped before the SP call.
  - complete/completed boolean aliases normalised → completedAt.

CHANGELOG v3.0
  - Added 'get_owners' to VALID_MODES and REQUIRED_BY_MODE (no required params).
  - get_owners generates: SELECT sp_activities(p_mode := 'get_owners') AS result;

CHANGELOG v2.0
  - Aligned with Activities Pre-Router v2.0 direct-route architecture.
  - completedAt passed explicitly (ISO string or None). None → NULL in SQL.
  - complete/completed boolean aliases still supported for AI Agent path.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTING_ONLY_PARAMS = {
    'shouldCallAPI', 'routerAction', 'message',
    'sessionId', 'chatHistory', 'currentMessage', 'originalBody',
}

VALID_PARAMS = {
    'mode',
    'activityId',
    'relatedType',
    'relatedId',
    'type',
    'subject',
    'description',
    'dueDate',
    'direction',
    'channel',
    'ownerId',
    'payload',
    'createdBy',
    'updatedBy',
    'pageSize',
    'pageNumber',
    'search',
    'dateFrom',
    'dateTo',
    'includeCompleted',
    'completedAt',
    'completed',
    'complete',
}

JSONB_PARAMS = {'payload'}

REQUIRED_BY_MODE: Dict[str, List[str]] = {
    'get':              ['activityId'],
    'update':           ['activityId'],
    'complete':         ['activityId'],
    'reopen':           ['activityId'],
    'delete':           ['activityId'],
    'create':           ['relatedType', 'relatedId', 'type', 'subject'],
    'log_call':         ['relatedType', 'relatedId', 'subject'],
    'log_email':        ['relatedType', 'relatedId', 'subject'],
    'schedule_meeting': ['relatedType', 'relatedId', 'subject', 'dueDate'],
    'create_task':      ['relatedType', 'relatedId', 'subject', 'dueDate'],
    'add_note':         ['relatedType', 'relatedId', 'subject'],
    'timeline':         ['relatedType', 'relatedId'],
    'list':             [],
    'overdue':          [],
    'upcoming':         [],
    'summary':          [],
    'get_owners':       [],
}

VALID_MODES = set(REQUIRED_BY_MODE.keys())

VALID_DIRECTIONS = {'inbound', 'outbound'}
VALID_CHANNELS   = {'phone', 'email', 'sms', 'voip', 'system', 'video'}

# Explicit remapping: camelCase key → exact pg param name (overrides default conversion)
PARAM_REMAP = {
    'dueDate':     'p_due_at',
    'completedAt': 'p_completed_at',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_value(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v.strip() == '')


def _camel_to_snake(name: str) -> str:
    """activityId → activity_id, pageSize → page_size."""
    import re
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def _to_pg_param(key: str) -> str:
    """Convert a camelCase key to p_snake_case, respecting explicit remaps."""
    if key in PARAM_REMAP:
        return PARAM_REMAP[key]
    if key.startswith('p_'):
        return key
    return f'p_{_camel_to_snake(key)}'


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _serialize(key: str, value: Any) -> str:
    """Serialise a parameter value for use in SQL (no type casts — SP accepts plain values)."""
    # Explicit NULL (e.g. completedAt=None for reopen)
    if value is None:
        return 'NULL'

    # JSONB
    if key in JSONB_PARAMS:
        if isinstance(value, (dict, list)):
            return f"'{_esc(json.dumps(value))}'::jsonb"
        return 'NULL'

    # datetime objects → ISO string
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"

    # Boolean (must come before int check — bool is subclass of int in Python)
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

    for req in REQUIRED_BY_MODE.get(mode, []):
        if not _has_value(params.get(req)):
            errors.append(f"Required parameter missing for mode '{mode}': '{req}'")

    # Range checks
    if params.get('pageSize') is not None:
        try:
            ps = int(params['pageSize'])
            if ps < 1 or ps > 200:
                errors.append('pageSize must be between 1 and 200')
        except (TypeError, ValueError):
            errors.append('pageSize must be an integer')

    if params.get('pageNumber') is not None:
        try:
            pn = int(params['pageNumber'])
            if pn < 1:
                errors.append('pageNumber must be >= 1')
        except (TypeError, ValueError):
            errors.append('pageNumber must be an integer')

    if params.get('includeCompleted') is not None and not isinstance(params['includeCompleted'], bool):
        errors.append('includeCompleted must be a boolean')

    if params.get('direction'):
        if str(params['direction']).lower() not in VALID_DIRECTIONS:
            errors.append(f"Invalid direction '{params['direction']}'. Allowed: {', '.join(sorted(VALID_DIRECTIONS))}")

    if params.get('channel'):
        if str(params['channel']).lower() not in VALID_CHANNELS:
            errors.append(f"Invalid channel '{params['channel']}'. Allowed: {', '.join(sorted(VALID_CHANNELS))}")

    for field in ('dateFrom', 'dateTo'):
        if params.get(field):
            try:
                datetime.fromisoformat(str(params[field]).replace('Z', '+00:00'))
            except ValueError:
                errors.append(f"Invalid {field} format (expected YYYY-MM-DD or ISO)")

    return errors


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_activities_query(params: Dict[str, Any]) -> Tuple[str, dict]:
    """
    Build `SELECT sp_activities(...) AS result;` from a camelCase params dict.

    Steps:
      1. Strip routing-only keys.
      2. Normalise complete/completed boolean aliases → completedAt.
      3. Validate mode + required fields.
      4. Serialise each param to SQL.

    Returns
    -------
    (sql, debug_info)

    Raises
    ------
    ValueError — on validation failure.
    """
    # 1. Strip routing-only keys and unknown keys (warn but don't block)
    clean: Dict[str, Any] = {}
    for k, v in params.items():
        if k in ROUTING_ONLY_PARAMS:
            continue
        if k not in VALID_PARAMS:
            logger.warning(f"Unknown parameter ignored: '{k}'")
            continue
        clean[k] = v

    # 2. Normalise complete/completed → completedAt  (AI Agent path)
    if 'complete' in clean:
        clean['completed'] = clean.pop('complete')
    if 'completed' in clean:
        val_completed = clean.pop('completed')
        if val_completed is True and clean.get('completedAt') is None:
            clean['completedAt'] = datetime.utcnow().isoformat()
        elif val_completed is False and clean.get('completedAt') is None:
            clean['completedAt'] = None   # explicit NULL → reopen

    mode = str(clean.get('mode') or '').lower().strip()
    logger.info(f"Building sp_activities query for mode='{mode}'")

    # 3. Validate
    errors = _validate(clean)
    if errors:
        msg = "Validation failed for sp_activities:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    # 4. Build named parameter list
    named: List[str] = []
    for key, value in clean.items():
        if key not in VALID_PARAMS:
            continue

        # Skip None values EXCEPT for completedAt (explicit NULL needed for reopen)
        if value is None and key != 'completedAt':
            continue

        pg_key = _to_pg_param(key)
        pg_val = _serialize(key, value)
        named.append(f"{pg_key} := {pg_val}")

    param_str = ', '.join(named)
    sql = f"SELECT sp_activities({param_str}) AS result;"

    debug_info = {
        'mode':        mode,
        'param_count': len(named),
        'params_used': [n.split(' := ')[0] for n in named],
    }

    logger.info(f"Built sp_activities query — {len(named)} params")
    logger.debug(f"SQL: {sql[:400]}")
    return sql, debug_info
