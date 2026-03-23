"""SQL Query Builder for sp_products — aligned with n8n Build SQL Query v4.3.

CHANGES IN v4.3:
  + p_image_url added to 'add', 'create', and 'update' cases.
    Mapped from p.imageUrl (forwarded by pre_router v2.1 from pd.image_url).
    sp_products v3f INSERTs / UPSERTs product_image (sort_order = 1) when
    this parameter is non-NULL.
  + 'image_url' added to _ALIAS_MAP so snake_case from AI Agent output
    is correctly resolved to imageUrl before SQL generation.

FROM v4.2:
  + No SQL generation changes required.  All 10 SP modes were already
    handled in v4.1.  This version documents the expanded routing surface:

  Pre-router v2.0 now routes the following EXTENDED product_direct_operation
  contexts directly here (was previously AI Agent territory):
    'inventory_summary'    → params.mode = 'inventory_summary'
    'low_stock_report'     → params.mode = 'low_stock'
    'price_matrix_report'  → params.mode = 'price_matrix'
    'price_history_report' → params.mode = 'price_history'
    'bulk_adjust_stock'    → params.mode = 'bulk_adjust_stock'
    'get_product_details'  → params.mode = 'get_details'
    'list_products'        → params.mode = 'list'

  All of these hit existing switch-case branches below without change.
  The context field (if present in params) is intentionally ignored here;
  only params.mode drives SQL generation.

FROM v4.1:
  + product_search case marked deprecated (Option A unification). Both the
    home-page search and the Create/Update Form typeahead now use MODE:list.
    The case is retained as a safety net only.

FROM v4.0:
  + 'create' mode: direct-form alias for 'add' with relaxed validation
    (SKU and description optional). Sent by product_direct_operation when
    context = 'create_product'.
  + p_retail_price:   mapped for 'add', 'create', 'update' from retailPrice.
  + p_promo_price:    mapped for 'add', 'create', 'update' from promoPrice.
  + p_category_name:  mapped in 'add', 'create', 'update' from categoryName.
  + p_status:         mapped in 'add', 'create', 'update' from status string.
    Both p_is_active (bool) and p_status (string) forwarded — SP uses
    p_status when present via v_is_active_resolved.
  + p_created_by / p_updated_by forwarded from createdBy / updatedBy.

The builder uses positional SQL (not named-param style) to exactly replicate
the JS version — every SP parameter is always emitted (NULL when absent).
The 'context' key is stripped before SQL generation (it's a routing hint only).
"""

import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(v) -> str:
    """SQL-escape a string; returns NULL for None/missing."""
    if v is None:
        return 'NULL'
    return f"'{str(v).replace(chr(39), chr(39)*2)}'"


def _bool(v) -> str:
    """Boolean literal; returns NULL when value is None."""
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    # Accept string 'true'/'false' from JSON
    if str(v).lower() == 'true':
        return 'TRUE'
    if str(v).lower() == 'false':
        return 'FALSE'
    return 'NULL'


def _num(v) -> str:
    """Numeric literal; returns NULL for None."""
    if v is None:
        return 'NULL'
    try:
        return str(float(v)) if '.' in str(v) else str(int(v))
    except (TypeError, ValueError):
        return 'NULL'


def _uuid(v) -> str:
    """UUID cast helper; returns NULL if absent."""
    if v:
        escaped = _esc(v)
        return f'{escaped}::UUID'
    return 'NULL'


# ── snake_case / alternate key normalisation ──────────────────────────────────
# The pre-router uses camelCase. The AI Agent may emit snake_case or alternate
# keys. We normalise before SQL generation.
_ALIAS_MAP = {
    'product_id':       'productId',
    'product_number':   'productNumber',
    'category_id':      'categoryId',
    'category_number':  'categoryNumber',
    'category_name':    'categoryName',
    'category_filter':  'categoryFilter',
    'is_active':        'isActive',
    'is_active_filter': 'isActiveFilter',
    'wholesale_price':  'wholesalePrice',
    'retail_price':     'retailPrice',
    'promo_price':      'promoPrice',
    'price_type':       'priceType',
    'price_value':      'priceValue',
    'stock_quantity':   'stockQuantity',
    'stock_adjustment': 'stockAdjustment',
    'low_stock_threshold': 'lowStockThreshold',
    'sku_filter':       'skuFilter',
    'name_filter':      'nameFilter',
    'sort_field':       'sortField',
    'sort_order':       'sortOrder',
    'created_by':       'createdBy',
    'updated_by':       'updatedBy',
    'image_url':        'imageUrl',        # v4.3
    'effective_from':   'effectiveFrom',
    'page_size':        'pageSize',
    'page_number':      'pageNumber',
}

VALID_MODES = {
    'add', 'create', 'update', 'get_details', 'list',
    'bulk_adjust_stock', 'inventory_summary', 'low_stock',
    'price_history', 'price_matrix', 'product_search',
}


def _normalise(raw: dict) -> dict:
    """Apply alias map (snake_case → camelCase) and strip 'context' routing hint."""
    out = {}
    for k, v in raw.items():
        if k == 'context':
            continue          # routing hint — never forwarded to SQL
        camel = _ALIAS_MAP.get(k, k)
        if camel not in out:  # first write wins
            out[camel] = v
    return out


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_products_query(params: Dict[str, Any]) -> Tuple[str, Dict]:
    """
    Build a SELECT sp_products(...) SQL string from params dict.

    Returns
    -------
    (sql, debug_info)

    Raises
    ------
    ValueError : Unknown or missing mode.
    """
    p = _normalise(params)
    mode = str(p.get('mode') or '').lower().strip()

    logger.info(f"Building sp_products query for mode='{mode}'")

    if not mode:
        raise ValueError("Parameter 'mode' is required")
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: '{mode}'. Allowed: {', '.join(sorted(VALID_MODES))}")

    sql = ''

    # ── add ───────────────────────────────────────────────────────────────────
    # AI-agent path — full validation (SKU, description, category all required).
    if mode == 'add':
        sql = f"""SELECT sp_products(
  p_mode            := 'add',
  p_product_number  := {_num(p.get('productNumber'))},
  p_sku             := {_esc(p.get('sku'))},
  p_name            := {_esc(p.get('name'))},
  p_description     := {_esc(p.get('description'))},
  p_category_id     := {_uuid(p.get('categoryId'))},
  p_category_number := {_num(p.get('categoryNumber'))},
  p_category_name   := {_esc(p.get('categoryName'))},
  p_is_active       := {_bool(p.get('isActive'))},
  p_status          := {_esc(p.get('status'))},
  p_stock           := {_num(p.get('stock'))},
  p_wholesale_price := {_num(p.get('wholesalePrice'))},
  p_retail_price    := {_num(p.get('retailPrice'))},
  p_promo_price     := {_num(p.get('promoPrice'))},
  p_price_type      := {_esc(p.get('priceType'))},
  p_price_value     := {_num(p.get('priceValue'))},
  p_currency        := {_esc(p.get('currency') or 'USD')},
  p_image_url       := {_esc(p['imageUrl']) if p.get('imageUrl') else 'NULL'},
  p_created_by      := {_esc(p.get('createdBy'))},
  p_payload         := NULL,
  p_effective_from  := NULL
);""".strip()

    # ── create ────────────────────────────────────────────────────────────────
    # Direct-form path — relaxed validation (SKU + description optional).
    # Sent by product_direct_operation when context = 'create_product'.
    elif mode == 'create':
        sql = f"""SELECT sp_products(
  p_mode            := 'create',
  p_name            := {_esc(p.get('name'))},
  p_sku             := {_esc(p.get('sku'))},
  p_description     := {_esc(p.get('description'))},
  p_category_id     := {_uuid(p.get('categoryId'))},
  p_category_number := {_num(p.get('categoryNumber'))},
  p_category_name   := {_esc(p.get('categoryName'))},
  p_status          := {_esc(p.get('status'))},
  p_stock           := {_num(p.get('stockQuantity'))},
  p_wholesale_price := {_num(p.get('wholesalePrice'))},
  p_retail_price    := {_num(p.get('retailPrice'))},
  p_promo_price     := {_num(p.get('promoPrice'))},
  p_currency        := {_esc(p.get('currency') or 'USD')},
  p_image_url       := {_esc(p['imageUrl']) if p.get('imageUrl') else 'NULL'},
  p_created_by      := {_esc(p.get('createdBy'))},
  p_payload         := NULL,
  p_effective_from  := NULL
);""".strip()

    # ── update ────────────────────────────────────────────────────────────────
    elif mode == 'update':
        sku_val  = f"{_esc(p['sku'])}" if p.get('sku') else 'NULL'
        name_val = f"{_esc(p['name'])}" if p.get('name') else 'NULL'
        desc_val = f"{_esc(p['description'])}" if p.get('description') else 'NULL'
        catn_val = f"{_esc(p['categoryName'])}" if p.get('categoryName') else 'NULL'
        ia_val   = _bool(p['isActive']) if p.get('isActive') is not None else 'NULL'
        stat_val = f"{_esc(p['status'])}" if p.get('status') else 'NULL'
        stock_val= _num(p['stock']) if p.get('stock') is not None else 'NULL'
        wp_val   = _num(p['wholesalePrice']) if p.get('wholesalePrice') is not None else 'NULL'
        rp_val   = _num(p['retailPrice'])    if p.get('retailPrice')    is not None else 'NULL'
        pp_val   = _num(p['promoPrice'])     if p.get('promoPrice')     is not None else 'NULL'
        pt_val   = f"{_esc(p['priceType'])}" if p.get('priceType') else 'NULL'
        pv_val   = _num(p['priceValue']) if p.get('priceValue') is not None else 'NULL'
        img_val  = _esc(p['imageUrl']) if p.get('imageUrl') else 'NULL'  # v4.3

        sql = f"""SELECT sp_products(
  p_mode            := 'update',
  p_product_id      := {_uuid(p.get('productId'))},
  p_product_number  := {_num(p.get('productNumber'))},
  p_sku             := {sku_val},
  p_name            := {name_val},
  p_description     := {desc_val},
  p_category_id     := {_uuid(p.get('categoryId'))},
  p_category_number := {_num(p.get('categoryNumber'))},
  p_category_name   := {catn_val},
  p_is_active       := {ia_val},
  p_status          := {stat_val},
  p_stock           := {stock_val},
  p_wholesale_price := {wp_val},
  p_retail_price    := {rp_val},
  p_promo_price     := {pp_val},
  p_price_type      := {pt_val},
  p_price_value     := {pv_val},
  p_currency        := {_esc(p.get('currency') or 'USD')},
  p_image_url       := {img_val},
  p_updated_by      := {_esc(p.get('updatedBy'))},
  p_payload         := NULL,
  p_effective_from  := NULL
);""".strip()

    # ── get_details ───────────────────────────────────────────────────────────
    elif mode == 'get_details':
        sql = f"""SELECT sp_products(
  p_mode           := 'get_details',
  p_product_id     := {_uuid(p.get('productId'))},
  p_product_number := {_num(p.get('productNumber'))},
  p_sku            := {_esc(p.get('sku')) if p.get('sku') else 'NULL'}
);""".strip()

    # ── list ──────────────────────────────────────────────────────────────────
    elif mode == 'list':
        iaf = p.get('isActiveFilter')
        iaf_sql = _bool(iaf) if iaf is not None else 'NULL'
        sql = f"""SELECT sp_products(
  p_mode             := 'list',
  p_search           := {_esc(p.get('search')) if p.get('search') else 'NULL'},
  p_category_filter  := {_uuid(p.get('categoryFilter'))},
  p_category_number  := {_num(p.get('categoryNumber'))},
  p_is_active_filter := {iaf_sql},
  p_sku_filter       := {_esc(p.get('skuFilter')) if p.get('skuFilter') else 'NULL'},
  p_name_filter      := {_esc(p.get('nameFilter')) if p.get('nameFilter') else 'NULL'},
  p_page_size        := {_num(p.get('pageSize') or 50)},
  p_page_number      := {_num(p.get('pageNumber') or 1)},
  p_sort_field       := {_esc(p.get('sortField')) if p.get('sortField') else 'NULL'},
  p_sort_order       := {_esc(p.get('sortOrder')) if p.get('sortOrder') else 'NULL'}
);""".strip()

    # ── bulk_adjust_stock ─────────────────────────────────────────────────────
    elif mode == 'bulk_adjust_stock':
        iaf = p.get('isActiveFilter')
        iaf_sql = _bool(iaf) if iaf is not None else 'NULL'
        sql = f"""SELECT sp_products(
  p_mode             := 'bulk_adjust_stock',
  p_stock_adjustment := {_num(p.get('stockAdjustment'))},
  p_category_filter  := {_uuid(p.get('categoryFilter'))},
  p_category_number  := {_num(p.get('categoryNumber'))},
  p_is_active_filter := {iaf_sql},
  p_sku_filter       := {_esc(p.get('skuFilter')) if p.get('skuFilter') else 'NULL'},
  p_name_filter      := {_esc(p.get('nameFilter')) if p.get('nameFilter') else 'NULL'}
);""".strip()

    # ── inventory_summary ─────────────────────────────────────────────────────
    elif mode == 'inventory_summary':
        sql = f"""SELECT sp_products(
  p_mode                := 'inventory_summary',
  p_category_filter     := {_uuid(p.get('categoryFilter'))},
  p_category_number     := {_num(p.get('categoryNumber'))},
  p_low_stock_threshold := {_num(p.get('lowStockThreshold') or 10)}
);""".strip()

    # ── low_stock ─────────────────────────────────────────────────────────────
    elif mode == 'low_stock':
        sql = f"""SELECT sp_products(
  p_mode                := 'low_stock',
  p_category_filter     := {_uuid(p.get('categoryFilter'))},
  p_category_number     := {_num(p.get('categoryNumber'))},
  p_low_stock_threshold := {_num(p.get('lowStockThreshold') or 10)}
);""".strip()

    # ── price_history ─────────────────────────────────────────────────────────
    elif mode == 'price_history':
        sql = f"""SELECT sp_products(
  p_mode           := 'price_history',
  p_product_id     := {_uuid(p.get('productId'))},
  p_product_number := {_num(p.get('productNumber'))}
);""".strip()

    # ── price_matrix ──────────────────────────────────────────────────────────
    elif mode == 'price_matrix':
        iaf = p.get('isActiveFilter')
        iaf_sql = _bool(iaf) if iaf is not None else 'NULL'
        sql = f"""SELECT sp_products(
  p_mode             := 'price_matrix',
  p_category_filter  := {_uuid(p.get('categoryFilter'))},
  p_category_number  := {_num(p.get('categoryNumber'))},
  p_is_active_filter := {iaf_sql},
  p_sku_filter       := {_esc(p.get('skuFilter')) if p.get('skuFilter') else 'NULL'},
  p_name_filter      := {_esc(p.get('nameFilter')) if p.get('nameFilter') else 'NULL'}
);""".strip()

    # ── product_search — DEPRECATED in v4.1 (Option A unification) ───────────
    # Both the home-page search and the Create/Update Form typeahead now route
    # to MODE:list via the pre-router. This case is retained as a safety net.
    elif mode == 'product_search':
        search = str(p.get('search') or '').strip()
        if len(search) < 2:
            raise ValueError("product_search requires a search term of at least 2 characters")
        sql = f"""SELECT sp_products(
  p_mode   := 'product_search',
  p_search := {_esc(search)}
);""".strip()

    else:
        raise ValueError(f"Unknown mode: '{mode}'")

    logger.info(f"Built sp_products query for mode='{mode}' (v4.3)")
    logger.debug(f"SQL: {sql[:300]}")

    debug_info = {
        'mode': mode,
        'sql_length': len(sql),
    }
    return sql, debug_info