"""Shared database connectivity for all CRM Agent modules.

Design
------
execute_sp(query)
    Generic executor for any stored procedure.  The query is a fully-built
    SQL string (e.g. SELECT sp_accounts(...) AS result) produced by the
    agent-specific sql_builder module.

    The column alias in the SELECT must always be ``result``.  Agent
    sql_builders already emit ``AS result``, so existing queries work
    unchanged.

Adding a new agent
------------------
No changes needed here.  The new agent's sql_builder emits a query ending
with ``... AS result;`` and calls execute_sp() directly.
"""

import json
import logging
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from .config import get_settings

logger = logging.getLogger(__name__)


# ── Connection factory ────────────────────────────────────────────────────────

def get_connection():
    """Return a raw psycopg2 connection using DB_DSN from settings."""
    settings = get_settings()
    return psycopg2.connect(settings.db_dsn)


# ── Generic SP executor ───────────────────────────────────────────────────────

def execute_sp(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Execute any stored-procedure query and return a list of row dicts.

    The query must alias its return value as ``result``::

        SELECT sp_accounts(p_mode := 'list') AS result;
        SELECT sp_contacts(p_mode := 'list') AS result;

    The ``result`` column value is parsed from JSONB/str → dict where
    possible.  Agents receive the same structure they produced when
    running standalone.

    Parameters
    ----------
    query  : Fully-formed SQL string produced by an agent's sql_builder.
    params : Optional dict of psycopg2 named parameters (rarely needed since
             queries are pre-built, but kept for future flexibility).

    Returns
    -------
    List of row dicts, each with a ``result`` key containing the SP response.
    """
    logger.info("Executing SP query")
    logger.debug(f"SQL: {query[:300]}...")

    try:
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

                results = []
                for row in rows:
                    row_dict = dict(row)
                    # Parse any JSONB / string columns into Python dicts
                    for key in row_dict:
                        val = row_dict[key]
                        if isinstance(val, str):
                            try:
                                row_dict[key] = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                pass
                    results.append(row_dict)

                conn.commit()
                logger.info(f"SP executed successfully — {len(results)} rows returned")
                return results

        finally:
            conn.close()

    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error executing SP: {e}")
        raise


# ── Health check ──────────────────────────────────────────────────────────────

def test_connection() -> bool:
    """Verify the DB is reachable.  Returns True on success."""
    try:
        conn = get_connection()
        conn.close()
        logger.info("Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False
