"""Store Formatter  v1.0

Formats sp_store / sp_products / sp_orders / sp_accounting responses
into structured JSON strings consumed directly by store-home.html.

Unlike the chat-module formatters (which produce human-readable text),
this formatter returns a JSON envelope that the store frontend parses
for rendering cards, grids, and forms.

Output envelope (always):
  {
    "status":      "success" | "error",
    "mode":        "<sp_name>/<mode>",
    "sp":          "<sp_name>",
    "data":        <SP response object>,
    "error":       "<message>"   (only on error)
  }

The web page receives this via response.output (JSON string), parses it,
and renders the appropriate UI section.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _first_result(db_rows: List[Dict]) -> Optional[Dict]:
    """Extract the first SP response dict from execute_sp() rows."""
    if not db_rows:
        return None
    row = db_rows[0]
    val = row.get("result") or row.get("sp_store") or row.get("sp_products") or row.get("sp_orders") or row.get("sp_accounting")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return {"raw": val}
    if isinstance(val, dict):
        return val
    # fallback — sometimes execute_sp unwraps the JSONB itself
    if isinstance(row, dict):
        for v in row.values():
            if isinstance(v, dict) and "metadata" in v:
                return v
    return None


def format_response(db_rows: List[Dict], params: Dict[str, Any]) -> str:
    """
    Format the store SP response into a JSON envelope string.
    Returns a JSON string; the router sets this as final_output.
    """
    sp   = params.get("sp", "unknown")
    mode = params.get("mode", "unknown")

    # ── checkout is assembled in graph.py db_node; db_rows already contains
    #    the assembled checkout result dict
    if mode == "checkout":
        # db_rows[0] is the assembled result dict from the multi-step checkout
        if db_rows and isinstance(db_rows[0], dict):
            result = db_rows[0]
            if result.get("error"):
                return json.dumps({
                    "status": "error",
                    "mode":   f"{sp}/{mode}",
                    "sp":     sp,
                    "error":  result["error"],
                    "data":   result,
                })
            return json.dumps({
                "status": "success",
                "mode":   f"{sp}/{mode}",
                "sp":     sp,
                "data":   result,
            })
        return json.dumps({"status": "error", "mode": f"{sp}/{mode}", "sp": sp,
                           "error": "Checkout produced no result"})

    data = _first_result(db_rows)

    if data is None:
        return json.dumps({
            "status": "error",
            "mode":   f"{sp}/{mode}",
            "sp":     sp,
            "error":  "No data returned from stored procedure",
        })

    meta = data.get("metadata") or {}
    if meta.get("status") == "error":
        return json.dumps({
            "status": "error",
            "mode":   f"{sp}/{mode}",
            "sp":     sp,
            "error":  meta.get("message", "SP returned error"),
            "code":   meta.get("code"),
            "data":   data,
        })

    return json.dumps({
        "status": "success",
        "mode":   f"{sp}/{mode}",
        "sp":     sp,
        "data":   data,
    })
