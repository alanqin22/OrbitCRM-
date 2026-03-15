"""SQL Query Builder for sp_notifications v2.0 — Python conversion of n8n Build SQL Query node.

Key design notes:
  - Parameters use camelCase (matching HTML chatInput fields).
  - Explicit remaps: employeeId → p_employee_uuid, notificationId → p_notification_uuid.
    (Unlike other CRM agents where the camelCase → snake_case conversion is automatic,
     the notifications SP uses UUID-suffixed parameter names.)
  - None values are serialised as NULL (no skip rule — all params are intentional).
  - Result column alias in SELECT is 'sp_notifications' (not 'result').
  - All 9 modes are deterministic; the AI Agent path also flows through this builder
    for backward-compat but routerAction=True is always set by the pre-router.

CHANGELOG v2.0
  - Aligned with notifications_pre_router_v2.js routerAction architecture.
  - All 9 SP modes now flow through this builder via routerAction = true.
  - Input arrives as params (from pre-router), never raw chatInput.
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

VALID_PARAMS = {
    'mode',
    'employeeId',
    'notificationId',
    'limit',
    'offset',
    'module',
    'search',
}

# Explicit remaps — notifications SP uses _uuid suffix, not plain _id
PARAM_REMAP = {
    'employeeId':     'p_employee_uuid',
    'notificationId': 'p_notification_uuid',
    'limit':          'p_limit',
    'offset':         'p_offset',
    'module':         'p_module',
    'search':         'p_search',
}

REQUIRED_BY_MODE: Dict[str, List[str]] = {
    'list':                 [],               # employeeId optional
    'unread_count':         ['employeeId'],
    'poll':                 ['employeeId'],
    'mark_all_read':        [],               # employeeId optional (scope)
    'mark_all_unread':      [],               # employeeId optional (scope)
    'click':                ['notificationId'],
    'mark_read':            ['notificationId'],
    'mark_unread':          ['notificationId'],
    'inspect_notification': ['notificationId'],
}

VALID_MODES = set(REQUIRED_BY_MODE.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_value(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v.strip() == '')


def _to_pg_param(key: str) -> str:
    """Map camelCase key to PostgreSQL parameter name."""
    if key in PARAM_REMAP:
        return PARAM_REMAP[key]
    if key.startswith('p_'):
        return key
    # Generic fallback (mode → p_mode)
    import re
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', key)
    snake = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    return f'p_{snake}'


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _serialize(value: Any) -> str:
    """Serialise a value for SQL. None → NULL."""
    if value is None:
        return 'NULL'
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'"
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, str):
        return f"'{_esc(value)}'"
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

    return errors


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_notifications_query(params: Dict[str, Any]) -> Tuple[str, dict]:
    """
    Build `SELECT sp_notifications(...) AS sp_notifications;` from params dict.

    Returns (sql, debug_info). Raises ValueError on validation failure.

    Notable differences from other CRM agents:
      - Result column alias is 'sp_notifications' (not 'result').
      - employeeId → p_employee_uuid (explicit remap, not camelCase→snake).
      - notificationId → p_notification_uuid (same).
      - None values serialise as NULL (not skipped as in Leads agent).
    """
    # Warn on unknown params
    clean: Dict[str, Any] = {}
    for k, v in params.items():
        if k not in VALID_PARAMS:
            logger.warning(f"Unknown parameter ignored: '{k}'")
            continue
        clean[k] = v

    mode = str(clean.get('mode') or '').lower().strip()
    logger.info(f"Building sp_notifications query for mode='{mode}'")

    errors = _validate(clean)
    if errors:
        msg = "Validation failed for sp_notifications:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    # Build named parameter list
    named: List[str] = []
    for key, value in clean.items():
        if key not in VALID_PARAMS:
            continue
        # Skip None values (let SP use its defaults) — except explicit NULL is fine
        if value is None:
            continue
        pg_key = _to_pg_param(key)
        pg_val = _serialize(value)
        named.append(f"{pg_key} := {pg_val}")

    param_str = ', '.join(named)
    # NOTE: result column alias is 'sp_notifications' (matches n8n formatter lookup)
    sql = f"SELECT sp_notifications({param_str}) AS sp_notifications;"

    debug_info = {
        'mode':        mode,
        'param_count': len(named),
        'params_used': [n.split(' := ')[0] for n in named],
    }

    logger.info(f"Built sp_notifications query — {len(named)} params")
    logger.debug(f"SQL: {sql[:400]}")
    return sql, debug_info
