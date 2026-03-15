"""SQL Query Builder for sp_accounting() — aligned with n8n Build SQL Query v8.7.

Key design: ALL 34 parameters are sent every call with explicit NULL::type
for unused parameters. This resolves PostgreSQL type inference errors.

Supports 14 modes.

v8.7 changes vs v8.6:
  NEW: contactId / p_contact_id parameter support.
    sp_accounting v2k added p_contact_id as an optional contact to stamp on
    the invoice row during generate_invoice (falls back to the first order's
    contact_id when not supplied).  The HTML form already reads gi_contact_id
    (auto-filled when user picks an account in the GI typeahead), and
    submitGenerateInvoice() now passes contactId — but the Build SQL Query
    node had no extractor or provided-block entry for it, so p_contact_id
    was always NULL.

    Changes:
      • Added contactId / contact_id aliases in _resolve_value for p_contact_id
      • Added p_contact_id to PARAM_DEFS after p_order_ids
      • Added p_contact_id: 'uuid' parameter type

  NEW: get_invoice_360 and get_payment_360 now arrive via pre-router direct
    path; no new BSQ changes needed since invoiceId and paymentId were
    already extracted and validated.

v8.6 changes vs v8.5:
  FIX: account_search now reads searchText / search_text aliases.
    The home-page Google-style Account Search Bar sends the typed query as
    chatInput.searchText (not chatInput.search).  Added searchText and
    search_text as fallback aliases in the search extractor.
    Priority: search → Search → searchText → search_text

v8.5 changes vs v8.4:
  FIX: Deep-unwrap AI agent tool-call envelope (three-tier priority).

v8.4 changes vs v8.3:
  NEW MODE: list_invoices_for_account

v8.3 changes vs v8.2:
  BUG FIX: mode extraction now also reads p_mode (AI agent alias).

v8.2 changes vs v8.1:
  NEW MODE: list_employee

v8.1 changes vs v8.0:
  FIX: adjustmentAmount reads 'adjustment' alias.
  FIX: ownerId reads 'owner' alias.
"""

import json
import re
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# VALID MODES (14 total — aligned with sp_accounting v2k+)
# ============================================================================
VALID_MODES = [
    'generate_invoice',
    'record_payment',
    'void_invoice',
    'list_invoices',
    'get_invoice_360',
    'list_payments',
    'get_payment_360',
    'account_balance',
    'account_balance_lookup',
    'accounting_summary',
    'account_search',               # v8.0 – lightweight typeahead
    'get_invoiceable_orders',       # v8.0 – uninvoiced orders for invoice form
    'list_employee',                # v8.2 – active employees dropdown
    'list_invoices_for_account',    # v8.4 – RP / Void Invoice form invoice dropdown
]

# ============================================================================
# ORDERED PARAMETER DEFINITIONS
# (name, pg_type, [camelCase / snake_case / AI aliases])
# v8.7: p_contact_id added after p_order_ids
# ============================================================================
PARAM_DEFS = [
    ('p_mode',                   'text',           ['mode', 'Mode', 'p_mode']),
    ('p_account_id',             'uuid',           ['accountId', 'account_id']),
    ('p_invoice_id',             'uuid',           ['invoiceId', 'invoice_id']),
    ('p_payment_id',             'uuid',           ['paymentId', 'payment_id']),
    ('p_order_ids',              'uuid[]',         ['orderIds', 'order_ids']),
    ('p_contact_id',             'uuid',           ['contactId', 'contact_id']),          # v8.7
    ('p_invoice_number',         'text',           ['invoiceNumber', 'invoice_number']),
    ('p_invoice_type',           'text',           ['invoiceType', 'invoice_type']),
    ('p_due_date',               'date',           ['dueDate', 'due_date']),
    ('p_status',                 'text',           ['status']),
    ('p_currency',               'text',           ['currency']),
    ('p_exchange_rate',          'numeric(18,6)',   ['exchangeRate', 'exchange_rate']),
    ('p_base_currency',          'text',           ['baseCurrency', 'base_currency']),
    ('p_tax_rate',               'numeric(5,4)',    ['taxRate', 'tax_rate']),
    ('p_discount_amount',        'numeric(18,2)',   ['discountAmount', 'discount_amount']),
    ('p_shipping_amount',        'numeric(18,2)',   ['shippingAmount', 'shipping_amount']),
    ('p_adjustment_amount',      'numeric(18,2)',   ['adjustmentAmount', 'adjustment_amount', 'adjustment']),  # v8.1
    ('p_amount',                 'numeric(18,2)',   ['amount']),
    ('p_payment_method',         'text',           ['paymentMethod', 'payment_method']),
    ('p_payment_source',         'text',           ['paymentSource', 'payment_source']),
    ('p_transaction_reference',  'text',           ['transactionReference', 'transaction_reference']),
    ('p_employee_uuid',          'uuid',           ['employeeUuid', 'employee_uuid']),
    ('p_owner_id',               'uuid',           ['ownerId', 'owner_id', 'owner']),                        # v8.1
    ('p_notes',                  'text',           ['notes']),
    ('p_metadata',               'jsonb',          ['metadata']),
    ('p_page_size',              'integer',        ['pageSize', 'page_size']),
    ('p_page_number',            'integer',        ['pageNumber', 'page_number']),
    # v8.6: searchText / search_text added as fallback aliases for home-page search bar
    ('p_search',                 'text',           ['search', 'Search', 'searchText', 'search_text']),
    ('p_start_date',             'date',           ['startDate', 'start_date']),
    ('p_end_date',               'date',           ['endDate', 'end_date']),
    ('p_year',                   'integer',        ['year']),
    ('p_status_filter',          'text',           ['statusFilter', 'status_filter']),
    ('p_sort_field',             'text',           ['sortField', 'sort_field']),
    ('p_sort_order',             'text',           ['sortOrder', 'sort_order']),
]

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
)


# ============================================================================
# HELPERS
# ============================================================================

def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == '':
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def _format_value(value, pg_type: str) -> str:
    """Format a Python value as a SQL literal with explicit type cast."""

    if value is None:
        return f"NULL::{pg_type}"

    if pg_type == 'uuid':
        uuid_str = str(value).strip().lower()
        if not UUID_PATTERN.match(uuid_str):
            raise ValueError(f"Invalid UUID: {uuid_str}")
        return f"'{uuid_str}'::{pg_type}"

    if pg_type == 'uuid[]':
        if not isinstance(value, list) or len(value) == 0:
            raise ValueError("UUID array is empty or invalid")
        clean = [
            str(v).strip().lower()
            for v in value
            if UUID_PATTERN.match(str(v).strip().lower())
        ]
        if not clean:
            raise ValueError("No valid UUIDs in array")
        items = "','".join(clean)
        return f"ARRAY['{items}']::{pg_type}"

    if pg_type.startswith('numeric'):
        num = float(value)
        return f"{num}::{pg_type}"

    if pg_type == 'integer':
        n = int(value)
        return f"{n}::{pg_type}"

    if pg_type == 'date':
        date_str = str(value).strip()
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            raise ValueError(f"Invalid date (YYYY-MM-DD): {date_str}")
        return f"'{date_str}'::{pg_type}"

    if pg_type == 'jsonb':
        if isinstance(value, dict):
            json_str = json.dumps(value).replace("'", "''")
        else:
            json_str = str(value).replace("'", "''")
        return f"'{json_str}'::{pg_type}"

    # Default: text
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'::{pg_type}"


def _resolve_value(payload: Dict[str, Any], keys: list) -> Any:
    """Return the first non-empty value matched from a list of key aliases."""
    for key in keys:
        val = payload.get(key)
        if not _is_empty(val):
            return val
    return None


# ============================================================================
# MAIN BUILDER
# ============================================================================

def build_accounting_query(params: Dict[str, Any]) -> Tuple[str, Optional[Dict]]:
    """
    Build the sp_accounting() call with ALL 34 parameters (v8.7).
    Unused parameters get explicit NULL::type casts.

    Three-tier payload unwrap (mirrors BSQ v8.5 fix):
      Tier 1: params.arguments.json — AI Agent tool-call envelope
      Tier 2: params.params         — pre-router direct params object
      Tier 3: params                — flat legacy / direct callers
    """
    # ── Tier 1: AI agent tool-call envelope ────────────────────────────────
    payload = params
    if 'params' in params and isinstance(params['params'], dict):
        p = params['params']
        if ('arguments' in p
                and isinstance(p['arguments'], dict)
                and 'json' in p['arguments']
                and isinstance(p['arguments']['json'], dict)):
            payload = p['arguments']['json']
            logger.debug('Unwrapped AI agent envelope → params.arguments.json')
        else:
            payload = p
            logger.debug('Unwrapped pre-router params object → params')
    else:
        logger.debug('Using flat item — no params wrapper detected')

    # ── Mode extraction (also accepts p_mode — AI agent alias) ─────────────
    mode = (
        str(payload.get('mode') or payload.get('Mode') or payload.get('p_mode') or '')
        .strip().lower()
    )

    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid or missing mode. Received: \"{mode or 'undefined'}\". "
            f"Allowed: {', '.join(VALID_MODES)}"
        )

    # ── Mode-specific required-field validation ─────────────────────────────
    account_id = _resolve_value(payload, ['accountId', 'account_id'])
    invoice_id = _resolve_value(payload, ['invoiceId', 'invoice_id'])
    payment_id = _resolve_value(payload, ['paymentId', 'payment_id'])
    order_ids  = _resolve_value(payload, ['orderIds', 'order_ids'])
    amount     = _resolve_value(payload, ['amount'])
    # v8.6: searchText / search_text added as fallback aliases
    search     = _resolve_value(payload, ['search', 'Search', 'searchText', 'search_text'])

    if mode == 'generate_invoice':
        if _is_empty(account_id):
            raise ValueError("generate_invoice requires accountId")
        if _is_empty(order_ids):
            raise ValueError("generate_invoice requires non-empty orderIds")

    if mode == 'record_payment':
        if _is_empty(invoice_id):
            raise ValueError("record_payment requires invoiceId")
        if _is_empty(amount) or float(amount) <= 0:
            raise ValueError("record_payment requires valid positive amount")

    if mode == 'void_invoice' and _is_empty(invoice_id):
        raise ValueError("void_invoice requires invoiceId")

    if mode == 'get_invoice_360' and _is_empty(invoice_id):
        raise ValueError("get_invoice_360 requires invoiceId")

    if mode == 'get_payment_360' and _is_empty(payment_id):
        raise ValueError("get_payment_360 requires paymentId")

    if mode == 'account_balance' and _is_empty(account_id):
        raise ValueError("account_balance requires accountId")

    if mode == 'account_balance_lookup' and _is_empty(search):
        raise ValueError("account_balance_lookup requires search")

    if mode == 'account_search' and _is_empty(search):
        raise ValueError("account_search requires search (minimum 2 characters recommended)")

    if mode == 'get_invoiceable_orders' and _is_empty(account_id):
        raise ValueError("get_invoiceable_orders requires accountId")

    if mode == 'list_invoices_for_account' and _is_empty(account_id):
        raise ValueError("list_invoices_for_account requires accountId")

    # list_employee requires no parameters beyond p_mode

    # ── Build all 34 parameters ─────────────────────────────────────────────
    sql_parts = []
    for param_name, pg_type, keys in PARAM_DEFS:
        value = _resolve_value(payload, keys)

        # Normalise mode to resolved lowercase value
        if param_name == 'p_mode':
            value = mode
        if param_name == 'p_currency' and value:
            value = str(value).upper()
        if param_name == 'p_sort_order' and value:
            value = str(value).upper()
        if param_name == 'p_sort_field' and value:
            value = str(value).lower()
        if param_name == 'p_status' and value:
            value = str(value).lower()
        if param_name == 'p_status_filter' and value:
            value = str(value).lower()

        formatted = _format_value(value if not _is_empty(value) else None, pg_type)
        sql_parts.append(f"    {param_name} := {formatted}")

    sql = "SELECT sp_accounting(\n" + ",\n".join(sql_parts) + "\n);"

    logger.info(f"Built query for mode '{mode}' (v8.7)")
    logger.debug(f"SQL:\n{sql}")

    return sql, None
