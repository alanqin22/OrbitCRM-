"""Store SQL Builder  v1.0

Builds fully-formed SQL strings for every store operation.

SP dispatch table:
  sp_products   — list, get_details
  sp_orders     — contact_search, create, update/batch_update, update/change_status, get_detail
  sp_store      — get_active_categories, get_invoice_by_order, get_product_metadata
  sp_accounting — get_invoice_360, account_balance

The checkout mode is special: it is NOT a single SQL call.
build_store_query() returns a sentinel dict for the checkout case so
graph.py's db_node can run the 3-step + Step D sequence itself.

All queries alias their return as ``result`` to match execute_sp().
"""

import logging
import json
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

CHECKOUT_SENTINEL = "__CHECKOUT__"


# ── Literal helpers ───────────────────────────────────────────────────────────

def _esc(v) -> str:
    if v is None:
        return "NULL"
    return f"'{str(v).replace(chr(39), chr(39)*2)}'"

def _uuid(v) -> str:
    if v:
        return f"'{str(v)}'::UUID"
    return "NULL"

def _num(v) -> str:
    if v is None:
        return "NULL"
    try:
        return str(int(v)) if str(v) == str(int(float(str(v)))) else str(float(v))
    except (TypeError, ValueError):
        return "NULL"

def _bool(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return "TRUE" if str(v).lower() == "true" else "FALSE"


# ── Alias normalisation (camelCase / snake_case → canonical) ──────────────────

_ALIAS = {
    "isActiveFilter":  "isActiveFilter",
    "is_active_filter":"isActiveFilter",
    "isSynthetic":     "isSynthetic",
    "is_synthetic":    "isSynthetic",
    "categoryFilter":  "categoryFilter",
    "category_filter": "categoryFilter",
    "category_id":     "categoryFilter",
    "productId":       "productId",
    "product_id":      "productId",
    "productNumber":   "productNumber",
    "product_number":  "productNumber",
    "orderId":         "orderId",
    "order_id":        "orderId",
    "orderNumber":     "orderNumber",
    "order_number":    "orderNumber",
    "accountId":       "accountId",
    "account_id":      "accountId",
    "contactId":       "contactId",
    "contact_id":      "contactId",
    "createdBy":       "createdBy",
    "created_by":      "createdBy",
    "updatedBy":       "updatedBy",
    "updated_by":      "updatedBy",
    "invoiceId":       "invoiceId",
    "invoice_id":      "invoiceId",
    "pageSize":        "pageSize",
    "page_size":       "pageSize",
    "pageNumber":      "pageNumber",
    "page_number":     "pageNumber",
    "sortField":       "sortField",
    "sort_field":      "sortField",
    "sortOrder":       "sortOrder",
    "sort_order":      "sortOrder",
}

def _norm(raw: dict) -> dict:
    out = {}
    for k, v in raw.items():
        canon = _ALIAS.get(k, k)
        if canon not in out:
            out[canon] = v
    return out


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_store_query(params: Dict[str, Any]) -> Tuple[str, Dict]:
    """
    Build a SQL string (or CHECKOUT_SENTINEL) from a routed params dict.

    Returns
    -------
    (sql_or_sentinel, debug_info)
    """
    p    = _norm(params)
    sp   = str(p.get("sp") or "").lower().strip()
    mode = str(p.get("mode") or "").lower().strip()

    logger.info(f"Building store query: sp='{sp}' mode='{mode}'")

    if not sp or not mode:
        raise ValueError("'sp' and 'mode' are required")

    # ── checkout — multi-step; handled in graph db_node ──────────────────────
    if sp == "checkout" and mode == "checkout":
        return CHECKOUT_SENTINEL, {"sp": "checkout", "mode": "checkout"}

    sql = ""

    # ==========================================================================
    # sp_products
    # ==========================================================================
    if sp == "sp_products":

        if mode == "list":
            iaf = _bool(p.get("isActiveFilter"))
            # NOTE: p_is_synthetic requires sp_products v3f patch to be applied.
            # Omit it here to stay compatible with the current unpatched sp_products.
            # Once sp_products_v3f_patch.sql is applied in Supabase, add back:
            #   p_is_synthetic := FALSE,
            sql = f"""SELECT sp_products(
  p_mode             := 'list',
  p_search           := {_esc(p.get("search"))},
  p_category_filter  := {_uuid(p.get("categoryFilter"))},
  p_is_active_filter := {iaf},
  p_page_size        := {_num(p.get("pageSize") or 24)},
  p_page_number      := {_num(p.get("pageNumber") or 1)},
  p_sort_field       := {_esc(p.get("sortField") or "name")},
  p_sort_order       := {_esc(p.get("sortOrder") or "ASC")}
) AS result;""".strip()

        elif mode == "get_details":
            sql = f"""SELECT sp_products(
  p_mode           := 'get_details',
  p_product_id     := {_uuid(p.get("productId"))},
  p_product_number := {_num(p.get("productNumber"))},
  p_sku            := {_esc(p.get("sku"))}
) AS result;""".strip()

        else:
            raise ValueError(f"sp_products: unsupported mode '{mode}'")

    # ==========================================================================
    # sp_orders
    # ==========================================================================
    elif sp == "sp_orders":

        if mode == "contact_search":
            sql = f"""SELECT sp_orders(
  p_mode   := 'contact_search',
  p_search := {_esc(p.get("search"))}
) AS result;""".strip()

        elif mode == "create":
            sql = f"""SELECT sp_orders(
  p_mode       := 'create',
  p_status     := 'Processing',
  p_account_id := {_uuid(p.get("accountId"))},
  p_contact_id := {_uuid(p.get("contactId"))},
  p_created_by := {_uuid(p.get("createdBy"))}
) AS result;""".strip()

        elif mode == "batch_update":
            # p_payload passed as JSONB literal
            payload = p.get("payload") or {}
            payload_sql = _esc(json.dumps(payload)) + "::JSONB"
            sql = f"""SELECT sp_orders(
  p_mode     := 'update',
  p_action   := 'batch_update',
  p_order_id := {_uuid(p.get("orderId"))},
  p_payload  := {payload_sql}
) AS result;""".strip()

        elif mode == "change_status":
            sql = f"""SELECT sp_orders(
  p_mode       := 'update',
  p_action     := 'change_status',
  p_order_id   := {_uuid(p.get("orderId"))},
  p_status     := 'Pending',
  p_updated_by := {_uuid(p.get("updatedBy"))}
) AS result;""".strip()

        elif mode in ("get_detail", "get_details"):
            sql = f"""SELECT sp_orders(
  p_mode         := 'get_detail',
  p_order_id     := {_uuid(p.get("orderId"))},
  p_order_number := {_esc(p.get("orderNumber"))}
) AS result;""".strip()

        else:
            raise ValueError(f"sp_orders: unsupported mode '{mode}'")

    # ==========================================================================
    # sp_store
    # ==========================================================================
    elif sp == "sp_store":

        if mode == "checkout_add_items":
            # Pass items as JSONB literal so the SP can loop over them
            items = p.get("items") or []
            items_sql = _esc(json.dumps(items)) + "::JSONB"
            sql = f"""SELECT sp_store(
  p_mode       := 'checkout_add_items',
  p_order_id   := {_uuid(p.get("orderId"))},
  p_items      := {items_sql},
  p_created_by := {_uuid(p.get("createdBy"))}
) AS result;""".strip()

        elif mode == "get_active_categories":
            sql = f"""SELECT sp_store(
  p_mode   := 'get_active_categories',
  p_search := {_esc(p.get("search"))}
) AS result;""".strip()

        elif mode == "get_invoice_by_order":
            sql = f"""SELECT sp_store(
  p_mode     := 'get_invoice_by_order',
  p_order_id := {_uuid(p.get("orderId"))}
) AS result;""".strip()

        elif mode == "get_product_metadata":
            sql = f"""SELECT sp_store(
  p_mode       := 'get_product_metadata',
  p_product_id := {_uuid(p.get("productId"))}
) AS result;""".strip()

        else:
            raise ValueError(f"sp_store: unsupported mode '{mode}'")

    # ==========================================================================
    # sp_accounting
    # ==========================================================================
    elif sp == "sp_accounting":

        if mode == "get_invoice_360":
            sql = f"""SELECT sp_accounting(
  p_mode       := 'get_invoice_360',
  p_invoice_id := {_uuid(p.get("invoiceId"))}
) AS result;""".strip()

        elif mode == "account_balance":
            sql = f"""SELECT sp_accounting(
  p_mode       := 'account_balance',
  p_account_id := {_uuid(p.get("accountId"))}
) AS result;""".strip()

        else:
            raise ValueError(f"sp_accounting: unsupported mode '{mode}'")

    else:
        raise ValueError(f"Unknown sp: '{sp}'")

    logger.info(f"Store query built: {len(sql)} chars")
    return sql, {"sp": sp, "mode": mode}
