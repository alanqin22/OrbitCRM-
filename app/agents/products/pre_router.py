"""Product Pre-Router — Python equivalent of n8n Pre Router v2.2.

Mirrors the order_pre_router_v3.2 architecture.

Inspects every incoming message and either ROUTES it directly to Build SQL
Query (router_action=True) or PASSES it through to the AI Agent
(router_action=False).

CHANGES IN v2.2 — Amazon-style search bar: list_categories support

  New context 'list_categories' routes to mode: 'list_categories'.
  Used by product_v26+ HTML on page load to populate the category dropdown
  in the Amazon-style search bar component via sp_products_list_categories().

CHANGES IN v2.1 — Image URL support

  create_product and update_product contexts now forward pd.image_url
  as imageUrl into the routed params object so sql_builder v4.4 can
  pass it as p_image_url to sp_products v3f, which INSERTs / UPSERTs
  a row in product_image (sort_order = 1).

CHANGES IN v2.0 — Maximum Direct SP Routing

  EXTENDED product_direct_operation handler:
    New context values route ALL read-only SP modes directly, bypassing
    the AI Agent entirely. The HTML page now uses these for every quick-
    action button instead of fillAndSend() with natural language.

    New contexts handled:
      'get_product_details'  → mode: get_details
      'list_products'        → mode: list
      'inventory_summary'    → mode: inventory_summary
      'low_stock_report'     → mode: low_stock
      'price_matrix_report'  → mode: price_matrix
      'price_history_report' → mode: price_history
      'bulk_adjust_stock'    → mode: bulk_adjust_stock

  EXTENDED TEXT-PATTERN ROUTES (fallback for voice / manual typing):
    Patterns added for: inventory summary, low stock, price matrix,
    price history, bulk stock adjustment, get details by UUID or #.

  AI AGENT is now invoked ONLY for:
    • Fully free-form natural-language queries with no deterministic
      parameter mapping (e.g., complex multi-field reasoning).
    • Delete product requests (no delete mode in sp_products).
    • Any product_direct_operation with an unrecognised context.

FROM v1.0:
  product_direct_operation for create_product / update_product.
  Text patterns: search products by name, show/get product details.
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_uuids(s: str) -> list:
    return UUID_RE.findall(str(s or ''))


def _to_num(v, cast=int):
    """Convert to numeric type; return None if absent/invalid."""
    if v is None or v == '':
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def _to_bool(v):
    """Convert to bool; return None if absent/invalid."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).lower() == 'true'


# ============================================================================
# ROUTER
# ============================================================================

def route_request(message: str, chat_input: dict) -> Dict[str, Any]:
    """
    Inspect the incoming message and return a routing decision dict.

    Routed:   { "router_action": True,  "params": { "mode": ..., ... } }
    Passthru: { "router_action": False }
    """
    raw = (message or '').strip()
    msg = raw.lower()

    logger.info('=== Product Pre-Router v2.2 ===')
    logger.info(f'Message: {raw[:120]}')

    # ── routerAction short-circuit (v3.1) ───────────────────────────────────
    # HTML direct-SP calls send routerAction=True + mode in chatInput with no
    # message text.  Detect this here before message-pattern matching so we
    # never fall through to the AI Agent (which needs Ollama / OpenAI).
    _SKIP = {'routerAction', 'message', 'sessionId', 'chatInput',
             'originalBody', 'webhookUrl', 'executionMode',
             'currentMessage', 'chatHistory'}
    if chat_input.get('routerAction') and chat_input.get('mode'):
        _params = {k: v for k, v in chat_input.items()
                   if k not in _SKIP and v is not None}
        logger.info(f'→ routerAction SHORT-CIRCUIT: mode={_params.get("mode")}')
        return {'router_action': True, 'params': _params}

    def routed(params: dict) -> dict:
        logger.info(f'→ ROUTED: mode={params.get("mode")} context={params.get("context", "")}')
        return {'router_action': True, 'params': params}

    def passthru(reason: Optional[str] = None) -> dict:
        logger.info(f'→ PASSTHRU: AI Agent {f"({reason})" if reason else ""}')
        return {'router_action': False}

    # ── product_direct_operation — highest priority ───────────────────────────
    # Sent by web page v11.0+ when Add Product / Update Product is clicked.
    # All structured data is in chatInput.productData.
    if chat_input.get('message') == 'product_direct_operation':
        pd = chat_input.get('productData') or {}

        if pd:
            context = pd.get('context')

            # ── Create Product ───────────────────────────────────────────────
            if context == 'create_product':
                params: Dict[str, Any] = {
                    'mode':           'create',
                    'context':        'create_product',
                    'name':           pd.get('name'),
                    'sku':            pd.get('sku') or None,
                    'categoryId':     pd.get('category_id') or None,
                    'categoryNumber': _to_num(pd.get('category_number'), int),
                    'categoryName':   pd.get('category_name') or None,
                    'retailPrice':    _to_num(pd.get('retail_price'), float),
                    'promoPrice':     _to_num(pd.get('promo_price'), float),
                    'wholesalePrice': _to_num(pd.get('wholesale_price'), float),
                    'stockQuantity':  _to_num(pd.get('stock_quantity'), int),
                    'description':    pd.get('description') or None,
                    'status':         pd.get('status') or 'Active',
                    'imageUrl':       pd.get('image_url') or None,   # v2.1
                    'createdBy':      pd.get('created_by') or chat_input.get('sessionId') or None
                }
                return routed(params)

            # ── Update Product ───────────────────────────────────────────────
            if context == 'update_product':
                params = {
                    'mode':           'update',
                    'context':        'update_product',
                    'productId':      pd.get('product_id'),
                    'name':           pd.get('name') or None,
                    'sku':            pd.get('sku') or None,
                    'categoryId':     pd.get('category_id') or None,
                    'categoryNumber': _to_num(pd.get('category_number'), int),
                    'categoryName':   pd.get('category_name') or None,
                    'retailPrice':    _to_num(pd.get('retail_price'), float),
                    'promoPrice':     _to_num(pd.get('promo_price'), float),
                    'wholesalePrice': _to_num(pd.get('wholesale_price'), float),
                    'stockQuantity':  _to_num(pd.get('stock_quantity'), int),
                    'description':    pd.get('description') or None,
                    'status':         pd.get('status') or None,
                    'imageUrl':       pd.get('image_url') or None,   # v2.1
                    'updatedBy':      pd.get('updated_by') or chat_input.get('sessionId') or None
                }
                return routed(params)

            # ── Get Product Details ──────────────────────────────────────────
            if context == 'get_product_details':
                if not pd.get('product_id') and pd.get('product_number') is None and not pd.get('sku'):
                    logger.warning('get_product_details: no identifier supplied')
                    return passthru('get_product_details missing identifier')
                params = {
                    'mode':          'get_details',
                    'productId':     pd.get('product_id') or None,
                    'productNumber': _to_num(pd.get('product_number'), int),
                    'sku':           pd.get('sku') or None
                }
                return routed(params)

            # ── List Products ────────────────────────────────────────────────
            if context == 'list_products':
                params = {
                    'mode':           'list',
                    'search':         pd.get('search') or None,
                    'categoryFilter': pd.get('category_id') or None,
                    'categoryNumber': _to_num(pd.get('category_number'), int),
                    'isActiveFilter': _to_bool(pd.get('is_active_filter')),
                    'skuFilter':      pd.get('sku_filter') or None,
                    'nameFilter':     pd.get('name_filter') or None,
                    'pageSize':       _to_num(pd.get('page_size'), int) or 50,
                    'pageNumber':     _to_num(pd.get('page_number'), int) or 1,
                    'sortField':      pd.get('sort_field') or None,
                    'sortOrder':      pd.get('sort_order') or None
                }
                return routed(params)

            # ── Inventory Summary ────────────────────────────────────────────
            if context == 'inventory_summary':
                params = {
                    'mode':              'inventory_summary',
                    'categoryFilter':    pd.get('category_id') or None,
                    'categoryNumber':    _to_num(pd.get('category_number'), int),
                    'lowStockThreshold': _to_num(pd.get('low_stock_threshold'), int) or 10
                }
                return routed(params)

            # ── Low Stock Report ─────────────────────────────────────────────
            if context == 'low_stock_report':
                params = {
                    'mode':              'low_stock',
                    'categoryFilter':    pd.get('category_id') or None,
                    'categoryNumber':    _to_num(pd.get('category_number'), int),
                    'lowStockThreshold': _to_num(pd.get('low_stock_threshold'), int) or 10,
                    'skuFilter':         pd.get('sku_filter') or None,
                    'nameFilter':        pd.get('name_filter') or None
                }
                return routed(params)

            # ── Price Matrix Report ──────────────────────────────────────────
            if context == 'price_matrix_report':
                params = {
                    'mode':           'price_matrix',
                    'categoryFilter': pd.get('category_id') or None,
                    'categoryNumber': _to_num(pd.get('category_number'), int),
                    'isActiveFilter': _to_bool(pd.get('is_active_filter')),
                    'skuFilter':      pd.get('sku_filter') or None,
                    'nameFilter':     pd.get('name_filter') or None
                }
                return routed(params)

            # ── Price History Report ─────────────────────────────────────────
            if context == 'price_history_report':
                if not pd.get('product_id') and pd.get('product_number') is None:
                    logger.warning('price_history_report: no product identifier supplied')
                    return passthru('price_history_report missing product identifier')
                params = {
                    'mode':          'price_history',
                    'productId':     pd.get('product_id') or None,
                    'productNumber': _to_num(pd.get('product_number'), int)
                }
                return routed(params)

            # ── Bulk Adjust Stock ────────────────────────────────────────────
            if context == 'bulk_adjust_stock':
                adj = _to_num(pd.get('stock_adjustment'), int)
                if adj is None or adj == 0:
                    logger.warning('bulk_adjust_stock: invalid or zero stock_adjustment')
                    return passthru('bulk_adjust_stock missing valid stock_adjustment')
                params = {
                    'mode':           'bulk_adjust_stock',
                    'stockAdjustment': adj,
                    'categoryFilter': pd.get('category_id') or None,
                    'categoryNumber': _to_num(pd.get('category_number'), int),
                    'isActiveFilter': _to_bool(pd.get('is_active_filter')),
                    'skuFilter':      pd.get('sku_filter') or None,
                    'nameFilter':     pd.get('name_filter') or None
                }
                return routed(params)

            # ── List Categories (NEW v2.2) — populates Amazon-style search dropdown
            if context == 'list_categories':
                return routed({'mode': 'list_categories'})

            logger.warning(f'product_direct_operation: unknown context: {context}')

    # ── Text-Pattern Routes ──────────────────────────────────────────────────
    # Fallback for voice input and manually typed messages that map 1-to-1 to
    # a deterministic SP mode. Order: most specific patterns checked first.

    # ── show all products / list products (no filter) ───────────────────────
    if re.match(r'^(show|list|display|get)\s+all\s+products?$', msg) or msg in ('list products', 'show products', 'all products'):
        return routed({'mode': 'list', 'pageSize': 50, 'pageNumber': 1})

    # ── list/show products in/by/for category [number] N ─────────────────────
    cat_list_match = re.match(
        r'^(?:show|list|display|get)\s+products?\s+(?:in|by|for|from)?\s*(?:category\s*(?:number\s*|#\s*)?)?(\d+)',
        msg, re.IGNORECASE
    ) or re.match(
        r'^(?:show|list|display|get)\s+products?\s+(?:in|by|for|from)\s+category\s*(?:number\s*|#\s*)?(\d+)',
        msg, re.IGNORECASE
    )
    if cat_list_match:
        return routed({'mode': 'list', 'categoryNumber': int(cat_list_match.group(1)), 'pageSize': 50, 'pageNumber': 1})

    # Also catch the reverse word order: "list category [number] N products"
    cat_rev_match = re.match(
        r'^(?:show|list|display|get)\s+category\s*(?:number\s*|#\s*)?(\d+)\s+products?',
        msg, re.IGNORECASE
    )
    if cat_rev_match:
        return routed({'mode': 'list', 'categoryNumber': int(cat_rev_match.group(1)), 'pageSize': 50, 'pageNumber': 1})

    # ── search products: <query> — unified MODE:list path ────────────────────
    # Used by BOTH the home-page search bar AND the Create/Update form typeahead.
    # MODE:list is fast enough for both — product_search is retired (Option A).
    if msg.startswith('search products by name') or msg.startswith('search products:'):
        if msg.startswith('search products:'):
            query = raw[len('search products:'):].strip()
        else:
            query = re.sub(r'search products by name\s*', '', raw, flags=re.IGNORECASE).strip()
        if len(query) >= 1:
            logger.info(f'[list/search] query: {query}')
            return routed({'mode': 'list', 'search': query, 'pageSize': 20, 'pageNumber': 1})

    # ── get / show product details for <uuid-or-number> ──────────────────────
    if msg.startswith('show product details for') or msg.startswith('get product details for'):
        ids = _extract_uuids(raw)
        num_match = re.search(r'(?:product\s+)?(?:number|#)\s*(\d+)', raw, re.IGNORECASE)
        if ids or num_match:
            params = {'mode': 'get_details'}
            if ids:
                params['productId'] = ids[0]
            if num_match:
                params['productNumber'] = int(num_match.group(1))
            return routed(params)

    # ── inventory summary ────────────────────────────────────────────────────
    if 'inventory summary' in msg or msg == 'show inventory' or msg == 'inventory summary':
        return routed({'mode': 'inventory_summary', 'lowStockThreshold': 10})

    # ── low stock ────────────────────────────────────────────────────────────
    if 'low stock' in msg or 'stock alert' in msg or 'out of stock' in msg:
        thresh_match = re.search(r'threshold\s+(?:of\s+)?(\d+)', raw, re.IGNORECASE)
        threshold = int(thresh_match.group(1)) if thresh_match else 10
        cat_num_match = re.search(r'category\s+(?:number\s+)?(\d+)', raw, re.IGNORECASE)
        category_number = int(cat_num_match.group(1)) if cat_num_match else None
        return routed({
            'mode': 'low_stock',
            'lowStockThreshold': threshold,
            'categoryNumber': category_number
        })

    # ── price matrix ─────────────────────────────────────────────────────────
    if 'price matrix' in msg:
        has_active = 'active' in msg
        is_active = re.search(r'\bactive\b', msg, re.IGNORECASE) and not re.search(r'inactive', msg, re.IGNORECASE)
        is_active_filter = True if has_active and is_active else None
        cat_num_match = re.search(r'category\s+(?:number\s+)?(\d+)', raw, re.IGNORECASE)
        category_number = int(cat_num_match.group(1)) if cat_num_match else None
        return routed({
            'mode': 'price_matrix',
            'isActiveFilter': is_active_filter,
            'categoryNumber': category_number
        })

    # ── price history ────────────────────────────────────────────────────────
    if 'price history' in msg:
        ids = _extract_uuids(raw)
        num_match = re.search(r'(?:product\s+)?(?:number|#)\s*(\d+)', raw, re.IGNORECASE)
        if ids or num_match:
            params = {'mode': 'price_history'}
            if ids:
                params['productId'] = ids[0]
            if num_match:
                params['productNumber'] = int(num_match.group(1))
            return routed(params)
        return passthru('price history: no product identifier in message')

    # ── bulk adjust / update stock ───────────────────────────────────────────
    bulk_match = re.match(r'^(increase|decrease|add|subtract|adjust|update)\s+stock\s+by\s+(\d+)', msg, re.IGNORECASE)
    if bulk_match:
        action = bulk_match.group(1).lower()
        sign = -1 if action in ('decrease', 'subtract') else 1
        adj = sign * int(bulk_match.group(2))
        cat_num_match = re.search(r'category\s+(?:number\s+)?(\d+)', raw, re.IGNORECASE)
        category_number = int(cat_num_match.group(1)) if cat_num_match else None
        cat_id = _extract_uuids(raw)
        category_filter = cat_id[0] if cat_id else None
        sku_match = re.search(r'sku\s+([A-Za-z0-9\-_]+)', raw, re.IGNORECASE)
        sku_filter = sku_match.group(1) if sku_match else None
        name_match = re.search(r'(?:named?|called)\s+"?([^"]+)"?', raw, re.IGNORECASE)
        name_filter = name_match.group(1) if name_match else None
        return routed({
            'mode': 'bulk_adjust_stock',
            'stockAdjustment': adj,
            'categoryNumber': category_number,
            'categoryFilter': category_filter,
            'skuFilter': sku_filter,
            'nameFilter': name_filter
        })

    # ── No match — AI Agent handles ───────────────────────────────────────────
    return passthru()
