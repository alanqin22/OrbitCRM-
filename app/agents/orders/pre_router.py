"""Orders Pre-Router v4.1 — Python conversion of n8n 'Pre Router' node.

OVERVIEW
  Routes every incoming request to either Build SQL Query (router_action=True)
  or the AI Agent (router_action=False).

  THREE routing paths:
    1. order_direct_operation — structured batchData from the web page (highest priority)
         • context='direct_query'  → generic params object stripped of context and sent directly
         • context='create_order'  → create mode with structured fields
         • action='batch_update'   → batch_update mode with payload JSONB
    2. Text prefix routes — deterministic NL-adjacent commands
    3. Passthru — AI Agent for everything else

DIRECT ROUTES (text prefix):
  "search accounts: <query>"              → account_search
  "search contacts: <query>"             → contact_search
  "list contacts for account <uuid>"     → contact_search (scoped)
  "get pricing for product <uuid> type X"→ get_pricing
  "list employees"                       → list_employees
  "show orders for account <uuid>"       → list (accountId filter)
  "show order <uuid>"                    → get_detail
  "get order <uuid>"                     → get_detail
  "view order <uuid>"                    → get_detail
  "find order <SO-YYYY-XXXXXX>"          → get_detail (by orderNumber)
  "find order <uuid>"                    → get_detail (by orderId)
  "show order details for order number…" → get_detail
  "show all orders" / "list orders" etc. → list
  "show deleted orders"                  → list with includeDeleted=True
  "show <status> orders"                 → list with status filter
  "sales summary"                        → sales_summary
  "account summary" / "show top spending"→ account_summary
  "category summary" / "analyze sales"   → category_summary
  "find orders for customer <name>"      → list with search
  "soft delete order <uuid>"             → update/soft_delete
  "delete order <uuid>"                  → update/soft_delete
  "restore order <uuid>"                 → update/restore
  "create order for account <uuid>"      → create
  "update order <uuid>"                  → update/update_header or change_status
  "list categories" / "get categories"   → get_category
  "list products" / "get products"       → get_product

CONTEXT FIELD:
  The 'context' field is a routing-only param injected by the web page:
    'direct_query'  — generic structured params, context stripped before routing
    'create_order'  — create mode with structured payload
    'create_add_items' — silent add-items after create (suppressed output in formatter)
    'update'        — regular batch update

CHANGELOG
  v4.1 — get_category, get_product text routes added.
  v4.0 — context='direct_query' universal direct path; many new text routes.
  v3.2 — context='create_order' structured payload.
  v3.1 — orderDate defaults to today if absent on create.
  v3.0 — Renamed trigger 'batch_update_order' → 'order_direct_operation'; context field.
  v2.0 — routerAction changed to boolean.
"""

from __future__ import annotations

import re
import logging
from datetime import date
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)
ORDER_NO_RE = re.compile(r'SO-\d{4}-\d{6}', re.IGNORECASE)

VALID_STATUSES = [
    'pending', 'processing', 'ready', 'invoiced',
    'shipped', 'delivered', 'completed', 'cancelled', 'refunded',
]

UUID_PARAMS = [
    'orderId', 'accountId', 'contactId', 'productId',
    'productPricingId', 'orderItemId', 'createdBy', 'updatedBy',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_uuid(s: Any) -> Optional[str]:
    """Strip trailing garbage (emojis, icons) from a UUID string."""
    m = UUID_RE.search(str(s or ''))
    return m.group(0) if m else None


def _sanitize_uuids(params: dict) -> dict:
    for key in UUID_PARAMS:
        if key in params and params[key]:
            cleaned = _clean_uuid(params[key])
            if cleaned:
                params[key] = cleaned
    return params


def _kv(text: str, key: str) -> Optional[str]:
    m = re.search(rf'{key}\s*=\s*["\']?([\w\-\.@]+)["\']?', text, re.IGNORECASE)
    return m.group(1) if m else None


def _uuids(text: str) -> list:
    return [m.group(0) for m in UUID_RE.finditer(text)]


def _order_numbers(text: str) -> list:
    return [m.group(0) for m in ORDER_NO_RE.finditer(text)]


def _today() -> str:
    return date.today().isoformat()


def _routed(params: dict) -> dict:
    logger.info(f"→ ROUTED: mode={params.get('mode')} action={params.get('action', '')}")
    return {'router_action': True, 'params': _sanitize_uuids(params)}


def _passthru() -> dict:
    logger.info('→ PASSTHRU: AI Agent')
    return {'router_action': False}


# ============================================================================
# MAIN ROUTER
# ============================================================================

def route_request(body: dict, chat_input: dict, session_id: str) -> dict:
    logger.info('=== Orders Pre-Router v4.1 ===')

    raw = (chat_input.get('message') or body.get('message') or '').strip()
    msg = raw.lower()
    logger.info(f'Message: {raw[:120]}')

    # ── 1. order_direct_operation — highest priority structured path ──────────
    if raw in ('order_direct_operation', 'batch_update_order') or \
       (chat_input.get('batchData', {}) or {}).get('action') == 'batch_update':

        bd = chat_input.get('batchData') or {}
        if bd:
            # ── direct_query: generic structured params from web page ─────────
            if bd.get('context') == 'direct_query':
                sp_params = {k: v for k, v in bd.items() if k != 'context'}
                logger.info(f"[direct_query] mode={sp_params.get('mode')}")
                return _routed(sp_params)

            # ── create_order: structured create payload ───────────────────────
            if bd.get('context') == 'create_order':
                qty = bd.get('quantity')
                params: dict = {
                    'mode':             'create',
                    'accountId':        bd.get('account_id'),
                    'status':           bd.get('status') or 'Pending',
                    'orderDate':        (bd.get('order_date') or _today()).split('T')[0],
                    'createdBy':        bd.get('created_by'),
                    'productId':        bd.get('product_id'),
                    'quantity':         int(qty) if qty is not None else None,
                    'priceType':        bd.get('price_type') or 'Retail',
                    'productPricingId': bd.get('product_pricing_id'),
                    'contactId':        bd.get('contact_id'),
                    'context':          'create_order',
                }
                # Drop None values
                params = {k: v for k, v in params.items() if v is not None}
                logger.info('[create_order] structured create')
                return _routed(params)

            # ── batch_update ──────────────────────────────────────────────────
            if bd.get('action') == 'batch_update':
                return _routed({
                    'mode':      'update',
                    'action':    'batch_update',
                    'orderId':   bd.get('order_id'),
                    'updatedBy': bd.get('updated_by'),
                    'payload':   bd.get('payload'),
                    'context':   bd.get('context') or 'update',
                })

    # ── 2. Text prefix routes ─────────────────────────────────────────────────

    # search accounts: <query>
    if msg.startswith('search accounts:'):
        query = raw[len('search accounts:'):].strip()
        if query:
            return _routed({'mode': 'account_search', 'search': query})

    # search contacts: <query>
    if msg.startswith('search contacts:'):
        query = raw[len('search contacts:'):].strip()
        if query:
            return _routed({'mode': 'contact_search', 'search': query})

    # list contacts for account <uuid>
    if msg.startswith('list contacts for account'):
        ids = _uuids(raw)
        if ids:
            return _routed({'mode': 'contact_search', 'accountId': ids[0]})

    # get pricing for product <uuid> type <priceType>
    if msg.startswith('get pricing for product'):
        ids = _uuids(raw)
        if ids:
            pt_m = re.search(r'type\s+(Retail|Wholesale|Promo)', raw, re.IGNORECASE)
            price_type = pt_m.group(1).capitalize() if pt_m else 'Retail'
            return _routed({'mode': 'get_pricing', 'productId': ids[0], 'priceType': price_type})

    # list employees
    if msg == 'list employees' or msg.startswith('list employees '):
        return _routed({'mode': 'list_employees'})

    # show orders for account <uuid>
    if msg.startswith('show orders for account'):
        ids = _uuids(raw)
        if ids:
            return _routed({
                'mode': 'list', 'accountId': ids[0],
                'includeDeleted': False, 'sortField': 'order_date',
                'sortOrder': 'DESC', 'pageSize': 50, 'pageNumber': 1,
            })

    # show order / get order / view order <uuid> → get_detail
    if msg.startswith(('show order ', 'get order ', 'view order ')):
        ids = _uuids(raw)
        if ids:
            return _routed({'mode': 'get_detail', 'orderId': ids[0]})

    # find order <SO-number> | find order <uuid>
    if msg.startswith('find order'):
        ons = _order_numbers(raw)
        if ons:
            return _routed({'mode': 'get_detail', 'orderNumber': ons[0]})
        ids = _uuids(raw)
        if ids:
            return _routed({'mode': 'get_detail', 'orderId': ids[0]})

    # show order details for order number <SO-...>
    if msg.startswith('show order details for order number'):
        ons = _order_numbers(raw)
        if ons:
            return _routed({'mode': 'get_detail', 'orderNumber': ons[0]})

    # show all orders / list orders / show orders (must precede status check)
    if msg in ('show all orders', 'show me all orders', 'list orders',
               'list all orders', 'show orders') or \
       msg.startswith(('show all orders', 'list all orders')):
        return _routed({
            'mode': 'list', 'includeDeleted': False,
            'sortField': 'order_date', 'sortOrder': 'DESC',
            'pageSize': 50, 'pageNumber': 1,
        })

    # show deleted orders
    if msg == 'show deleted orders' or msg.startswith('show deleted orders'):
        return _routed({
            'mode': 'list', 'includeDeleted': True,
            'sortField': 'order_date', 'sortOrder': 'DESC',
            'pageSize': 50, 'pageNumber': 1,
        })

    # show <status> orders
    for s in VALID_STATUSES:
        if msg == f'show {s} orders' or msg.startswith(f'show {s} orders'):
            return _routed({
                'mode': 'list',
                'status': s.capitalize(),
                'includeDeleted': False,
                'sortField': 'order_date', 'sortOrder': 'DESC',
                'pageSize': 50, 'pageNumber': 1,
            })

    # sales summary
    if msg == 'sales summary' or msg.startswith('sales summary'):
        yr_raw = _kv(raw, 'year')
        params = {'mode': 'sales_summary'}
        if yr_raw and yr_raw.isdigit():
            yr = int(yr_raw)
            if 1900 <= yr <= 3000:
                params['year'] = yr
        return _routed(params)

    # account summary / show top spending customers
    if msg in ('account summary',) or \
       msg.startswith(('account summary', 'show top spending', 'top spending customers', 'analyze accounts')):
        yr_raw = _kv(raw, 'year')
        params = {'mode': 'account_summary'}
        if yr_raw and yr_raw.isdigit():
            yr = int(yr_raw)
            if 1900 <= yr <= 3000:
                params['year'] = yr
        return _routed(params)

    # category summary / analyze sales by category
    if msg in ('category summary',) or \
       msg.startswith(('category summary', 'analyze sales by category', 'sales by category')):
        yr_raw = _kv(raw, 'year')
        params = {'mode': 'category_summary'}
        if yr_raw and yr_raw.isdigit():
            yr = int(yr_raw)
            if 1900 <= yr <= 3000:
                params['year'] = yr
        return _routed(params)

    # find orders for customer <name>
    if msg.startswith(('find orders for customer', 'orders for customer')):
        prefix = 'find orders for customer' if msg.startswith('find orders for customer') \
            else 'orders for customer'
        search_term = raw[len(prefix):].strip()
        if search_term:
            return _routed({
                'mode': 'list', 'search': search_term,
                'includeDeleted': False,
                'sortField': 'order_date', 'sortOrder': 'DESC',
                'pageSize': 50, 'pageNumber': 1,
            })

    # soft delete order <uuid>
    if msg.startswith('soft delete order'):
        ids = _uuids(raw)
        if ids:
            p = {'mode': 'update', 'action': 'soft_delete', 'orderId': ids[0]}
            upd = _kv(raw, 'updatedBy') or _kv(raw, 'updated_by')
            if upd:
                p['updatedBy'] = upd
            return _routed(p)

    # delete order <uuid>
    if msg.startswith('delete order'):
        ids = _uuids(raw)
        if ids:
            p = {'mode': 'update', 'action': 'soft_delete', 'orderId': ids[0]}
            upd = _kv(raw, 'updatedBy') or _kv(raw, 'updated_by')
            if upd:
                p['updatedBy'] = upd
            return _routed(p)

    # restore order <uuid>
    if msg.startswith('restore order'):
        ids = _uuids(raw)
        if ids:
            p = {'mode': 'update', 'action': 'restore', 'orderId': ids[0]}
            upd = _kv(raw, 'updatedBy') or _kv(raw, 'updated_by')
            if upd:
                p['updatedBy'] = upd
            return _routed(p)

    # create order for account <uuid>
    if msg.startswith('create order for account'):
        ids = _uuids(raw)
        if ids:
            p: dict = {'mode': 'create', 'accountId': ids[0]}
            contact_id  = _kv(raw, 'contact')   or _kv(raw, 'contactId')
            product_id  = _kv(raw, 'product')   or _kv(raw, 'productId')
            qty         = _kv(raw, 'quantity')  or _kv(raw, 'qty')
            ptype       = _kv(raw, 'priceType') or _kv(raw, 'price_type')
            status      = _kv(raw, 'status')
            created_by  = _kv(raw, 'createdBy') or _kv(raw, 'created_by')
            pricing_id  = _kv(raw, 'pricingId') or _kv(raw, 'productPricingId')
            if contact_id: p['contactId']        = contact_id
            if product_id: p['productId']        = product_id
            if qty:        p['quantity']         = int(qty)
            if ptype:      p['priceType']        = ptype
            if status:     p['status']           = status
            if created_by: p['createdBy']        = created_by
            if pricing_id: p['productPricingId'] = pricing_id
            od = _kv(raw, 'orderDate') or _kv(raw, 'order_date')
            p['orderDate'] = od.split('T')[0] if od else _today()
            return _routed(p)

    # update order <uuid>
    if msg.startswith('update order'):
        ids = _uuids(raw)
        if ids:
            status      = _kv(raw, 'status')
            contact_id  = _kv(raw, 'contact') or _kv(raw, 'contactId')
            updated_by  = _kv(raw, 'updatedBy') or _kv(raw, 'updated_by')
            # change_status if only status changing; otherwise update_header
            action = _kv(raw, 'action') or (
                'change_status' if status and not contact_id else 'update_header'
            )
            p = {'mode': 'update', 'action': action, 'orderId': ids[0]}
            if status:     p['status']    = status
            if contact_id: p['contactId'] = contact_id
            if updated_by: p['updatedBy'] = updated_by
            return _routed(p)

    # list categories / get categories → get_category
    if msg in ('list categories', 'get categories') or \
       msg.startswith(('list categories', 'get categories')):
        p = {'mode': 'get_category'}
        q = _kv(raw, 'search')
        if q:
            p['search'] = q
        return _routed(p)

    # list products / get products → get_product
    if msg in ('list products', 'get products') or \
       msg.startswith(('list products', 'get products')):
        ids = _uuids(raw)
        p = {'mode': 'get_product'}
        if ids:
            p['categoryId'] = ids[0]
        q = _kv(raw, 'search')
        if q:
            p['search'] = q
        return _routed(p)

    # ── 3. Passthru → AI Agent ────────────────────────────────────────────────
    return _passthru()
