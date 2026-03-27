"""Store Graph  v1.0

Simplified 3-node LangGraph topology — no AI Agent, no parse node.

    pre_router ──[direct_db]──→ db ──→ format ──→ END
               └──[error]──────────────────────→ END

Because every store operation is deterministic, the AI agent and parse nodes
from build_standard_graph() are not needed.  We build a custom graph here.

The db_node has special handling for the checkout 'mode':
  Step A — sp_orders create (status='Processing')
  Step B — sp_store checkout_add_items (add all items with computed line values)
  Step C — sp_orders change_status → 'Pending' (fires trigger cascade)
  Step D — sp_store get_invoice_by_order (captures auto-created invoice)

All other modes are a single execute_sp() call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from langgraph.graph import StateGraph, END

from app.core.graph_utils import AgentState
from app.core.database import execute_sp

from .pre_router import route_request
from .sql_builder import build_store_query, CHECKOUT_SENTINEL
from .formatter import format_response

logger = logging.getLogger(__name__)


# ============================================================================
# NODES
# ============================================================================

def pre_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-Router — all store requests are deterministic, always routed."""
    logger.info("=== Store Pre-Router Node ===")
    user_input = state.get("user_input", "")
    chat_input = state.get("chat_input", {})

    result = route_request(user_input, chat_input)

    if result["router_action"]:
        params = result["params"]
        logger.info(f"Store pre-router ROUTED → sp={params.get('sp')} mode={params.get('mode')}")
        return {**state, "router_action": True, "parsed_json": params, "should_call_api": True}

    logger.warning("Store pre-router UNRECOGNISED — returning error")
    return {**state, "router_action": False, "should_call_api": False,
            "final_output": json.dumps({
                "status": "error",
                "mode":   "unknown",
                "sp":     "unknown",
                "error":  f"Unrecognised store context: {chat_input.get('storeData', {}).get('context', 'none')}",
            })}


def db_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Database node.

    Standard modes  → single execute_sp() call.
    Checkout mode   → 4-step sequence (A/B/C/D) with compensation on failure.
    """
    logger.info("=== Store DB Node ===")

    if not state.get("should_call_api"):
        return state

    params = state.get("parsed_json") or {}
    mode   = params.get("mode", "")
    sp     = params.get("sp", "")

    # ── CHECKOUT — multi-step ─────────────────────────────────────────────────
    if sp == "checkout" and mode == "checkout":
        return _checkout_node(state, params)

    # ── STANDARD — single SP call ─────────────────────────────────────────────
    try:
        query, _ = build_store_query(params)
        db_rows  = execute_sp(query)
        logger.info(f"Store SP returned {len(db_rows)} rows")
        return {**state, "db_rows": db_rows}
    except Exception as exc:
        logger.error(f"Store DB error: {exc}", exc_info=True)
        error_row = [{"result": {
            "metadata": {"status": "error", "code": -500, "message": str(exc)}
        }}]
        return {**state, "db_rows": error_row}


def _checkout_node(state: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Runs the 4-step checkout sequence and returns assembled result in db_rows.

    Step A — create order (status='Processing')   → no trigger
    Step B — sp_store checkout_add_items            → trgfn_order_items_update_order
    Step C — change_status → 'Pending'             → full trigger cascade
    Step D — get_invoice_by_order                  → captures auto-created invoice
    """
    order_id     = None
    order_number = None

    def _exec(sql: str) -> Dict:
        rows = execute_sp(sql)
        return (rows[0].get("result") or {}) if rows else {}

    def _sp_ok(data: Dict) -> bool:
        return (data.get("metadata") or {}).get("status") == "success"

    # ── Step A: create order as 'Processing' ─────────────────────────────────
    try:
        query_a, _ = build_store_query({
            "sp":        "sp_orders",
            "mode":      "create",
            "accountId": params["accountId"],
            "contactId": params.get("contactId"),
            "createdBy": params.get("createdBy"),
        })
        data_a = _exec(query_a)
        if not _sp_ok(data_a):
            msg = (data_a.get("metadata") or {}).get("message", "create failed")
            return {**state, "db_rows": [{"error": msg, "step": "A"}]}

        order_obj    = data_a.get("order") or {}
        order_id     = order_obj.get("order_id")
        order_number = order_obj.get("order_number")

        if not order_id:
            return {**state, "db_rows": [{"error": "Step A: no order_id returned", "step": "A"}]}

        logger.info(f"Checkout Step A OK — order_id={order_id} order_number={order_number}")

    except Exception as exc:
        logger.error(f"Checkout Step A failed: {exc}", exc_info=True)
        return {**state, "db_rows": [{"error": f"Step A: {exc}", "step": "A"}]}

    # ── Step B: checkout_add_items — insert items with computed line values ────
    #
    # WHY NOT sp_orders(batch_update):
    #   batch_update inserts order_items without line_subtotal/line_total/description.
    #   trgfn_order_items_update_order computes: orders.total_amount = SUM(NULL) = 0.
    #   Zero flows into the invoice trigger guard → $0 invoice, no auto-payment.
    #
    # sp_store(checkout_add_items) inserts each item with:
    #   description   = product name (from products table)
    #   line_subtotal = qty × retail price  ← trigger reads this correctly
    #   line_total    = qty × retail price
    #   discount      = 0.00
    #   After each INSERT, trgfn_order_items_update_order accumulates the real total.
    # ─────────────────────────────────────────────────────────────────────────
    try:
        import json as _json
        items_list = [
            {"product_id": item["product_id"], "quantity": int(item["quantity"])}
            for item in (params.get("items") or [])
        ]

        query_b, _ = build_store_query({
            "sp":        "sp_store",
            "mode":      "checkout_add_items",
            "orderId":   order_id,
            "items":     items_list,
            "createdBy": params.get("createdBy"),
        })
        data_b = _exec(query_b)
        if not _sp_ok(data_b):
            msg = (data_b.get("metadata") or {}).get("message", "checkout_add_items failed")
            try:
                from .sql_builder import _uuid
                execute_sp(f"""SELECT sp_orders(
                  p_mode := 'update', p_action := 'change_status',
                  p_order_id := {_uuid(order_id)}, p_status := 'Cancelled'
                ) AS result;""")
                logger.info(f"Compensation cancel sent for order {order_id}")
            except Exception:
                pass
            return {**state, "db_rows": [{"error": msg, "step": "B",
                                           "order_id": order_id, "order_number": order_number}]}

        items_inserted = data_b.get("items_inserted", 0)
        skipped = data_b.get("skipped_items", [])
        if skipped:
            logger.warning(f"Checkout Step B: {len(skipped)} item(s) skipped: {skipped}")
        logger.info(f"Checkout Step B OK — {items_inserted} item(s) inserted via checkout_add_items")

    except Exception as exc:
        logger.error(f"Checkout Step B failed: {exc}", exc_info=True)
        return {**state, "db_rows": [{"error": f"Step B: {exc}", "step": "B",
                                       "order_id": order_id, "order_number": order_number}]}

    # ── Step C: change_status → 'Pending' — fires trigger cascade ────────────
    try:
        query_c, _ = build_store_query({
            "sp":        "sp_orders",
            "mode":      "change_status",
            "orderId":   order_id,
            "updatedBy": params.get("createdBy"),
        })
        data_c = _exec(query_c)
        if not _sp_ok(data_c):
            msg = (data_c.get("metadata") or {}).get("message", "change_status failed")
            return {**state, "db_rows": [{"error": msg, "step": "C",
                                           "order_id": order_id, "order_number": order_number}]}
        logger.info("Checkout Step C OK — status→Pending, trigger cascade fired")

    except Exception as exc:
        logger.error(f"Checkout Step C failed: {exc}", exc_info=True)
        return {**state, "db_rows": [{"error": f"Step C: {exc}", "step": "C",
                                       "order_id": order_id, "order_number": order_number}]}

    # ── Step D: capture the auto-created invoice ──────────────────────────────
    invoice_id     = None
    invoice_number = None
    invoice_status = "issued"
    total_amount   = None
    currency       = None

    try:
        query_d, _ = build_store_query({
            "sp":      "sp_store",
            "mode":    "get_invoice_by_order",
            "orderId": order_id,
        })
        data_d = _exec(query_d)
        if _sp_ok(data_d):
            inv            = data_d.get("invoice") or {}
            invoice_id     = inv.get("invoice_id")
            invoice_number = inv.get("invoice_number")
            total_amount   = inv.get("total_amount")
            currency       = inv.get("currency")
            invoice_status = inv.get("status", "issued")
            logger.info(f"Checkout Step D OK — invoice_id={invoice_id} "
                        f"invoice_number={invoice_number} status={invoice_status} "
                        f"total={total_amount}")
        else:
            invoice_status = "issued"
            logger.warning("Checkout Step D: invoice lookup failed (order created successfully)")

    except Exception as exc:
        logger.warning(f"Checkout Step D warning: {exc}")

    # ── Assemble success result ───────────────────────────────────────────────
    result = {
        "order_id":       order_id,
        "order_number":   order_number,
        "invoice_id":     invoice_id,
        "invoice_number": invoice_number,
        "invoice_status": invoice_status,   # 'paid' when trigger chain ran correctly
        "total_amount":   total_amount,
        "currency":       currency,
    }
    return {**state, "db_rows": [result]}


def formatter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Formatter node — converts db_rows to JSON envelope for the store HTML."""
    logger.info("=== Store Formatter Node ===")
    try:
        db_rows    = state.get("db_rows") or []
        parsed_json = state.get("parsed_json") or {}

        if state.get("should_call_api"):
            final_output = format_response(db_rows, parsed_json)
        else:
            # pre_router already set final_output for error cases
            final_output = state.get("final_output") or json.dumps({
                "status": "error", "mode": "unknown", "sp": "unknown",
                "error":  "No operation performed",
            })

        return {**state, "final_output": final_output}

    except Exception as exc:
        logger.error(f"Store formatter error: {exc}", exc_info=True)
        return {**state, "final_output": json.dumps({
            "status": "error", "mode": "format", "sp": "unknown",
            "error":  f"Formatter error: {exc}",
        })}


# ============================================================================
# GRAPH SINGLETON — custom 3-node topology (no AI agent)
# ============================================================================

_graph_app = None


def get_graph():
    global _graph_app
    if _graph_app is None:
        logger.info("Building Store LangGraph (3-node, no AI agent)...")

        graph = StateGraph(AgentState)
        graph.add_node("pre_router", pre_router_node)
        graph.add_node("db",         db_node)
        graph.add_node("format",     formatter_node)

        graph.set_entry_point("pre_router")

        def _route_after_pre_router(state):
            # Always go to db — error state is handled inside db_node
            return "db"

        graph.add_conditional_edges(
            "pre_router",
            _route_after_pre_router,
            {"db": "db"},
        )
        graph.add_edge("db",     "format")
        graph.add_edge("format", END)

        _graph_app = graph.compile()
        logger.info("Store LangGraph built successfully")
    return _graph_app
