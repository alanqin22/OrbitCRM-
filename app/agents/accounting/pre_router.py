"""Accounting Pre-Router — Python equivalent of n8n pre-router v3.4.

Mirrors the n8n 'pre router' Code node (v3.4).

OVERVIEW
  Inspects every incoming message and either:
    • ROUTES directly to Build SQL Query (router_action = True)  — deterministic
    • Passes through to the AI Agent   (router_action = False)   — free-text NL

  DESIGN PRINCIPLE: Every SP mode that accepts deterministic parameters
  MUST be handled here. The AI Agent is invoked ONLY as a last resort for
  free-form natural-language queries that cannot be structured here.

KEY TRIGGERS (all produce router_action = True)
  "account search:"                            → account_search
  "account balance:"                           → account_balance
  "Search accounts by name <query>"            → account_search
  "List invoices for account <uuid>"           → list_invoices_for_account
  "Get invoiceable orders for account <uuid>"  → get_invoiceable_orders
  "list employees active"                      → list_employee
  "list filtered:"                             → list_invoices | list_payments | accounting_summary
  "generate invoice:"                          → generate_invoice
  "record payment:"                            → record_payment
  "void invoice:"                              → void_invoice
  "get invoice 360:"                           → get_invoice_360       (v3.4)
  "get payment 360:"                           → get_payment_360       (v3.4)
  All other messages                           → Passthru → AI Agent

CHANGELOG
  v3.4 — Added "get invoice 360:" → get_invoice_360
              and "get payment 360:" → get_payment_360 direct routes.
         All 14 SP modes now have a deterministic path; AI Agent is pure fallback.
  v3.3 — Added home-page Google-style Account Search Bar routes:
           "account search:" → account_search (searchText from chatInput)
           "account balance:" → account_balance (accountId from chatInput)
         Updated list_filtered to support account_summary → accounting_summary.
  v3.2 — Added AccountingFilterBar direct route:
           "list filtered:" → list_invoices | list_payments
  v3.1 — Added four UI-lookup direct routes:
           "Search accounts by name <query>"           → account_search
           "List invoices for account <uuid>"          → list_invoices_for_account
           "Get invoiceable orders for account <uuid>" → get_invoiceable_orders
           "list employees active"                     → list_employee
  v3.0 — Added direct routes for generate_invoice / record_payment / void_invoice.
"""

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)


# ============================================================================
# HELPERS
# ============================================================================

def _extract_uuid(s: str) -> Optional[str]:
    """Return the first UUID found in *s*, or None."""
    m = UUID_PATTERN.search(str(s))
    return m.group(0) if m else None


def _val(v: Any) -> Any:
    """Coerce empty string / None to None; pass everything else through."""
    if v is None or v == '':
        return None
    return v


def _build_passthru_message(raw: str, chat_input: dict) -> str:
    """
    Build the normalised AI Agent message by appending any structured
    chatInput fields — mirrors the n8n passthru() helper and the v6
    preprocessor.py logic.
    """
    current = raw
    if chat_input.get('city'):
        current += f", city {chat_input['city']}"
    if chat_input.get('pageSize') is not None:
        current += f", page size {chat_input['pageSize']}"
    if chat_input.get('pageNumber') is not None:
        current += f", page number {chat_input['pageNumber']}"
    if chat_input.get('customerId'):
        current += f", customer ID {chat_input['customerId']}"
    return current.strip()


# ============================================================================
# MAIN ROUTER
# ============================================================================

def route_request(message: str, chat_input: dict) -> Dict[str, Any]:
    """
    Inspect the incoming message and return a routing decision dict:

    Routed (deterministic):
        {
            "router_action": True,
            "params": { "mode": "...", ... }   ← fed directly into sql_builder
        }

    Passthru (AI Agent handles):
        {
            "router_action": False,
            "current_message": "<preprocessed message string>"
        }

    Parameters
    ----------
    message     : Raw message string from chatInput.message
    chat_input  : Full chatInput dict (all structured fields)
    """
    raw = (message or '').strip()
    msg = raw.lower()

    logger.info('=== Accounting Pre-Router v3.4 ===')
    logger.info(f'Message: {raw}')

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
        logger.info(f'→ ROUTED: mode={params.get("mode")} params={str(params)[:200]}')
        return {'router_action': True, 'params': params}

    def passthru() -> dict:
        current_message = _build_passthru_message(raw, chat_input)
        logger.info(f'→ PASSTHRU: AI Agent | currentMessage: {current_message}')
        return {'router_action': False, 'current_message': current_message}

    # ── Home-Page Account Search Bar: account_search  (v3.3) ─────────────────
    #   Source: _homeSearchAccounts() — message prefix "account search:"
    #   chatInput.searchText = typed query (2+ chars)
    if msg.startswith('account search:'):
        query = (chat_input.get('searchText') or '').strip()
        if len(query) >= 2:
            logger.info(f'[account_search / home bar] searchText: {query}')
            return routed({'mode': 'account_search', 'searchText': query})
        logger.warning(f'[account_search / home bar] query too short ("{query}") — passthru')
        return passthru()

    # ── Home-Page Account Search Bar: account_balance  (v3.3) ────────────────
    #   Source: _homeSelectAccount() — message prefix "account balance:"
    #   chatInput.accountId = selected account UUID
    if msg.startswith('account balance:'):
        account_id = _val(chat_input.get('accountId')) or _extract_uuid(raw)
        if account_id:
            logger.info(f'[account_balance / home bar] accountId: {account_id}')
            return routed({'mode': 'account_balance', 'accountId': account_id})
        logger.warning('[account_balance / home bar] no accountId — falling through to AI Agent')
        # fall through to passthru below

    # ── Account Search  (v3.1) ────────────────────────────────────────────────
    #   Source: _giSearchAccounts() / _sharedSearchAccounts()
    #   Message: "Search accounts by name <query>"
    if msg.startswith('search accounts by name '):
        query = raw[len('search accounts by name '):].strip()
        if len(query) >= 2:
            logger.info(f'[account_search] query: {query}')
            return routed({'mode': 'account_search', 'search': query})
        logger.warning(f'[account_search] query too short ("{query}") — falling through')

    # ── List Invoices for Account  (v3.1) ─────────────────────────────────────
    #   Source: _loadInvoicesForAccount()
    #   Message: "List invoices for account <uuid>"
    if msg.startswith('list invoices for account '):
        account_id = _extract_uuid(raw)
        if account_id:
            logger.info(f'[list_invoices_for_account] accountId: {account_id}')
            return routed({'mode': 'list_invoices_for_account', 'accountId': account_id})
        logger.warning('[list_invoices_for_account] no UUID found — falling through')

    # ── Get Invoiceable Orders for Account  (v3.1) ────────────────────────────
    #   Source: _giLoadInvoiceableOrders()
    #   Message: "Get invoiceable orders for account <uuid>"
    if msg.startswith('get invoiceable orders for account '):
        account_id = _extract_uuid(raw)
        if account_id:
            logger.info(f'[get_invoiceable_orders] accountId: {account_id}')
            return routed({'mode': 'get_invoiceable_orders', 'accountId': account_id})
        logger.warning('[get_invoiceable_orders] no UUID found — falling through')

    # ── List Employees  (v3.1) ────────────────────────────────────────────────
    #   Source: _loadEmployeesFromAgent()
    #   Message: "list employees active" (exact, case-insensitive)
    if msg == 'list employees active':
        logger.info('[list_employee] direct route')
        return routed({'mode': 'list_employee'})

    # ── AccountingFilterBar: List Filtered  (v3.2) ───────────────────────────
    #   Source: applyFilters()
    #   Message prefix: "list filtered:"
    #   chatInput: listingType, startDate, endDate
    if msg.startswith('list filtered:'):
        listing_type = (chat_input.get('listingType') or 'invoice').lower().strip()
        if listing_type == 'payment':
            mode = 'list_payments'
        elif listing_type == 'account_summary':
            mode = 'accounting_summary'
        else:
            mode = 'list_invoices'
        logger.info(f'[list_filtered] listingType: {listing_type} | mode: {mode}')
        return routed({
            'mode':      mode,
            'startDate': _val(chat_input.get('startDate')),
            'endDate':   _val(chat_input.get('endDate')),
        })

    # ── Generate Invoice  (v3.0) ──────────────────────────────────────────────
    #   Source: submitGenerateInvoice()
    #   Message prefix: "generate invoice:"
    if msg.startswith('generate invoice:'):
        if not chat_input.get('accountId') or not chat_input.get('orderIds'):
            logger.warning('[generate_invoice] Missing required fields — passthru to AI Agent')
            return passthru()
        logger.info(
            f'[generate_invoice] accountId: {chat_input.get("accountId")} '
            f'| orderIds: {chat_input.get("orderIds")} '
            f'| contactId: {chat_input.get("contactId")} '
            f'| employeeUuid: {chat_input.get("employeeUuid")}'
        )
        return routed({
            'mode':           'generate_invoice',
            'accountId':      _val(chat_input.get('accountId')),
            'orderIds':       _val(chat_input.get('orderIds')),
            'contactId':      _val(chat_input.get('contactId')),        # v8.7 / v3.4
            'invoiceNumber':  _val(chat_input.get('invoiceNumber')),
            'invoiceType':    _val(chat_input.get('invoiceType')),
            'dueDate':        _val(chat_input.get('dueDate')),
            'currency':       _val(chat_input.get('currency')) or 'CAD',
            'taxRate':        _val(chat_input.get('taxRate')),
            'discountAmount': _val(chat_input.get('discountAmount')),
            'shippingAmount': _val(chat_input.get('shippingAmount')),
            'adjustment':     _val(chat_input.get('adjustment')),
            'ownerId':        _val(chat_input.get('ownerId')),
            'employeeUuid':   _val(chat_input.get('employeeUuid')),
            'notes':          _val(chat_input.get('notes')),
        })

    # ── Record Payment  (v3.0) ────────────────────────────────────────────────
    #   Source: submitRecordPayment()
    #   Message prefix: "record payment:"
    if msg.startswith('record payment:'):
        if not chat_input.get('invoiceId') or not chat_input.get('amount'):
            logger.warning('[record_payment] Missing required fields — passthru to AI Agent')
            return passthru()
        logger.info(
            f'[record_payment] invoiceId: {chat_input.get("invoiceId")} '
            f'| amount: {chat_input.get("amount")} '
            f'| method: {chat_input.get("paymentMethod")} '
            f'| employeeUuid: {chat_input.get("employeeUuid")}'
        )
        return routed({
            'mode':                 'record_payment',
            'invoiceId':            _val(chat_input.get('invoiceId')),
            'amount':               _val(chat_input.get('amount')),
            'paymentMethod':        _val(chat_input.get('paymentMethod')),
            'paymentSource':        _val(chat_input.get('paymentSource')),
            'currency':             _val(chat_input.get('currency')) or 'CAD',
            'transactionReference': _val(chat_input.get('transactionReference')),
            'ownerId':              _val(chat_input.get('ownerId')),
            'employeeUuid':         _val(chat_input.get('employeeUuid')),
            'notes':                _val(chat_input.get('notes')),
        })

    # ── Void Invoice  (v3.0) ──────────────────────────────────────────────────
    #   Source: submitVoidInvoice()
    #   Message prefix: "void invoice:"
    if msg.startswith('void invoice:'):
        if not chat_input.get('invoiceId'):
            logger.warning('[void_invoice] Missing invoiceId — passthru to AI Agent')
            return passthru()
        logger.info(
            f'[void_invoice] invoiceId: {chat_input.get("invoiceId")} '
            f'| employeeUuid: {chat_input.get("employeeUuid")}'
        )
        return routed({
            'mode':         'void_invoice',
            'invoiceId':    _val(chat_input.get('invoiceId')),
            'employeeUuid': _val(chat_input.get('employeeUuid')),
            'notes':        _val(chat_input.get('notes')),
        })

    # ── Get Invoice 360  (v3.4) ───────────────────────────────────────────────
    #   Source: actions.getInvoice360() / "View Invoice" buttons
    #   Message prefix: "get invoice 360:"
    #   chatInput.invoiceId = invoice UUID
    if msg.startswith('get invoice 360:'):
        invoice_id = _val(chat_input.get('invoiceId')) or _extract_uuid(raw)
        if invoice_id:
            logger.info(f'[get_invoice_360] invoiceId: {invoice_id}')
            return routed({'mode': 'get_invoice_360', 'invoiceId': invoice_id})
        logger.warning('[get_invoice_360] no invoiceId found — falling through to AI Agent')

    # ── Get Payment 360  (v3.4) ───────────────────────────────────────────────
    #   Source: actions.getPayment360() / "View Payment" buttons
    #   Message prefix: "get payment 360:"
    #   chatInput.paymentId = payment UUID
    if msg.startswith('get payment 360:'):
        payment_id = _val(chat_input.get('paymentId')) or _extract_uuid(raw)
        if payment_id:
            logger.info(f'[get_payment_360] paymentId: {payment_id}')
            return routed({'mode': 'get_payment_360', 'paymentId': payment_id})
        logger.warning('[get_payment_360] no paymentId found — falling through to AI Agent')

    # ── All other messages → AI Agent ─────────────────────────────────────────
    return passthru()
