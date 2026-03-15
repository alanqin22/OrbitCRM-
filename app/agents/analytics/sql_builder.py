"""SQL Query Builder for sp_analytics_dashboard v2.0.

Key design notes:
  - Only one SP mode: 'dashboard'. The reportType param selects which
    sections to return; omitting it (NULL) returns the full dashboard.
  - Parameter order MUST match the SP argument list exactly:
      startDate → p_start_date  (DATE)
      endDate   → p_end_date    (DATE)
      ownerId   → p_owner_id    (UUID)
      accountId → p_account_id  (UUID)
      productId → p_product_id  (UUID)
      reportType → p_report_type (TEXT) — NEW in SP v3e
  - ALL params are always emitted in the fixed order, even as NULL.
    This is different from the Leads agent (which skips None values) and
    matches the original n8n builder which always included all 6 params.
  - The SP result column has no explicit alias in the original n8n query,
    so psycopg2 returns it under 'sp_analytics_dashboard'. The database
    executor and formatter both handle that key.
  - AR Aging snapshot mode: startDate and endDate are omitted entirely
    (not passed as NULL) when the pre-router uses ar_aging without dates.

CHANGELOG v2.0
  - Added reportType → p_report_type parameter (SP v3e selective sections).
  - When NULL the SP returns all sections (full dashboard).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixed parameter order MUST match SP argument list
PG_PARAM_ORDER = [
    'startDate',    # → p_start_date  DATE
    'endDate',      # → p_end_date    DATE
    'ownerId',      # → p_owner_id    UUID
    'accountId',    # → p_account_id  UUID
    'productId',    # → p_product_id  UUID
    'reportType',   # → p_report_type TEXT  (SP v3e+)
]

VALID_PARAMS = set(PG_PARAM_ORDER)

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_value(v: Any) -> bool:
    return v is not None and not (isinstance(v, str) and v.strip() == '')


def _to_pg_param(key: str) -> str:
    """camelCase → p_snake_case."""
    if key.startswith('p_'):
        return key
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', key)
    snake = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    return f'p_{snake}'


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _serialize(key: str, value: Any) -> str:
    """Serialise a param value for SQL. None → NULL."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return str(value)
    # All string values (dates, UUIDs, report types) are single-quoted
    return f"'{_esc(str(value))}'"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(params: dict) -> List[str]:
    errors: List[str] = []

    # AI Agent always produces mode='dashboard'; pre-router may omit mode
    mode = str(params.get('mode') or 'dashboard').lower().strip()
    if mode != 'dashboard':
        errors.append(f"Invalid mode: '{mode}'. Only 'dashboard' is supported.")
        return errors

    # Date format checks (when provided)
    for date_key in ('startDate', 'endDate'):
        v = params.get(date_key)
        if _has_value(v) and not DATE_RE.match(str(v)):
            errors.append(f"'{date_key}' must be YYYY-MM-DD format, got: '{v}'")

    # UUID format checks (when provided)
    for uuid_key in ('ownerId', 'accountId', 'productId'):
        v = params.get(uuid_key)
        if _has_value(v) and not UUID_RE.match(str(v)):
            errors.append(f"'{uuid_key}' must be a valid UUID, got: '{v}'")

    return errors


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_analytics_query(params: Dict[str, Any]) -> Tuple[str, dict]:
    """
    Build `SELECT sp_analytics_dashboard(p_start_date := ..., ...) ;` from params.

    Returns (sql, debug_info). Raises ValueError on validation failure.

    Key behaviours:
      - Params emitted in fixed PG_PARAM_ORDER (matches SP argument list).
      - 'mode' key consumed but not forwarded to SP (no p_mode parameter).
      - AR Aging snapshot: if startDate/endDate absent, they emit as NULL.
      - reportType='full_dashboard' → omitted from params before this call
        (pre-router strips it); the SQL will emit NULL for p_report_type.
      - All 6 named params always included in the SQL for SP compatibility.
    """
    # Warn on unknown params
    for k in params:
        if k not in VALID_PARAMS and k != 'mode':
            logger.warning(f"Unknown parameter ignored: '{k}'")

    # Strip 'mode' — sp_analytics_dashboard has no p_mode argument
    clean = {k: v for k, v in params.items() if k in VALID_PARAMS}

    errors = _validate(params)
    if errors:
        msg = "Validation failed for sp_analytics_dashboard:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(msg)
        raise ValueError(msg)

    mode       = str(params.get('mode') or 'dashboard').lower()
    start_date = clean.get('startDate')
    end_date   = clean.get('endDate')
    report_type = clean.get('reportType')

    logger.info(
        f"Building sp_analytics_dashboard query — mode={mode} "
        f"startDate={start_date} endDate={end_date} reportType={report_type}"
    )

    # Build named params in SP argument order
    named: List[str] = []
    for key in PG_PARAM_ORDER:
        value    = clean.get(key)          # None if absent
        pg_key   = _to_pg_param(key)
        pg_val   = _serialize(key, value)  # None → 'NULL'
        named.append(f"{pg_key} := {pg_val}")

    sql = f"SELECT sp_analytics_dashboard({', '.join(named)});"

    debug_info = {
        'mode':         mode,
        'report_type':  report_type,
        'start_date':   start_date,
        'end_date':     end_date,
        'param_count':  len(named),
        'params_used':  [n.split(' := ')[0] for n in named],
    }

    logger.info(f"Built sp_analytics_dashboard query — {len(named)} params")
    logger.debug(f"SQL: {sql[:400]}")
    return sql, debug_info
