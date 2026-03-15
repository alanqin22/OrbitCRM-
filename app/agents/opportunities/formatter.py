"""Response formatter for Opportunities — Python conversion of n8n Format Response v3.3.

v3.1  — Opportunity ID column added to list table.
v3.2  — productLines in detail payload; get_owners mode.
v3.3  — LIST mode: added Lead Source and Owner columns.

All modes:
  list, get, create, update, change_stage, close_won, close_lost,
  add_product, update_product, remove_product,
  pipeline, forecast,
  search_accounts, search_products, search_opportunities,
  get_owners, delete, generic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_num(n, fallback: float = 0.0) -> float:
    try:
        return float(n)
    except (TypeError, ValueError):
        return fallback


def _fmt_currency(n, currency: str = 'USD') -> str:
    return f'${_safe_num(n):,.2f}'


def _fmt_big(n) -> str:
    return f'{_safe_num(n):,.0f}'


def _fmt_dt(value) -> str:
    if not value:
        return 'N/A'
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.strftime('%b %d, %Y %I:%M %p')
    except (ValueError, AttributeError):
        return str(value) or 'N/A'


def _fmt_date(value) -> str:
    if not value:
        return 'N/A'
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.strftime('%b %d, %Y')
    except (ValueError, AttributeError):
        return str(value) or 'N/A'


def _fmt_pct(n, decimals: int = 2) -> str:
    return f'{_safe_num(n) * 100:.{decimals}f}%'


def _trunc_uuid(u) -> str:
    s = str(u) if u else ''
    return (s[:8] + '...') if len(s) > 8 else s or 'N/A'


def _parse_response(db_rows: List[Dict]) -> Dict:
    if not db_rows:
        return {}
    first = db_rows[0]
    for key in ('result', 'sp_opportunities'):
        val = first.get(key)
        if val is not None:
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except json.JSONDecodeError:
                    pass
            elif isinstance(val, dict):
                return val
    return first


def _md_header(columns: List[str]) -> str:
    sep = '| ' + ' | '.join('---' for _ in columns) + ' |'
    return '| ' + ' | '.join(columns) + ' |\n' + sep


def _md_row(values: List) -> str:
    return '| ' + ' | '.join(str(v) for v in values) + ' |'


def _stage_icon(stage: str) -> str:
    return {
        'prospecting':   '🔍',
        'qualification': '📋',
        'proposal':      '📝',
        'negotiation':   '💼',
        'closed_won':    '🎉',
        'closed_lost':   '📉',
    }.get(stage or '', '•')


def _health_icon(h: str) -> str:
    return {
        'excellent': '🟢',
        'good':      '🔵',
        'fair':      '🟡',
        'poor':      '🟠',
    }.get(h or '', '🔴')


def _sort_desc_by_revenue(arr: list) -> list:
    def key(r):
        return (_safe_num(r.get('forecast_revenue')), _safe_num(r.get('historical_revenue')))
    return sorted(arr, key=key, reverse=True)


def _mode_name(mode: str) -> str:
    return {
        'list':                 'Opportunity List',
        'get':                  'Opportunity Details',
        'create':               'Opportunity Created',
        'update':               'Opportunity Updated',
        'change_stage':         'Stage Changed',
        'close_won':            'Opportunity Closed - Won! 🎉',
        'close_lost':           'Opportunity Closed - Lost',
        'add_product':          'Product Added',
        'update_product':       'Product Updated',
        'remove_product':       'Product Removed',
        'search_accounts':      'Account Search',
        'search_products':      'Product Search',
        'search_opportunities': 'Opportunity Search',
        'pipeline':             'Sales Pipeline Summary',
        'forecast':             'Revenue Forecast',
        'delete':               'Opportunity Deleted',
    }.get(mode, 'Unknown')


# ── Detail renderer (shared by get, create, update) ──────────────────────────

def _render_opportunity_detail(out: list, opp: dict, products: list, stage_history: list):
    """Render a full opportunity detail block into the out list."""
    out.append(f'**{opp.get("name") or "Untitled Opportunity"}**')
    out.append('')

    out.append(_md_header(['Field', 'Value']))
    out.append(_md_row(['Opportunity ID',  opp.get('opportunity_id') or 'N/A']))
    out.append(_md_row(['Amount',         f'**{_fmt_currency(opp.get("amount", 0))}**']))
    out.append(_md_row(['Stage',           opp.get('stage') or 'N/A']))
    out.append(_md_row(['Probability',     f'{opp.get("probability", 0)}%']))

    weighted = _safe_num(opp.get('amount')) * _safe_num(opp.get('probability')) / 100
    out.append(_md_row(['Weighted Value',  _fmt_currency(weighted)]))
    out.append(_md_row(['Status',          opp.get('status') or 'N/A']))
    out.append(_md_row(['Close Date',      _fmt_date(opp.get('close_date'))]))

    if opp.get('account_name'): out.append(_md_row(['Account',      opp['account_name']]))
    if opp.get('contact_name'): out.append(_md_row(['Contact',      opp['contact_name']]))
    if opp.get('lead_source'):  out.append(_md_row(['Lead Source',  opp['lead_source']]))
    if opp.get('description'):  out.append(_md_row(['Description',  opp['description']]))
    out.append(_md_row(['Created At',  _fmt_dt(opp.get('created_at'))]))
    out.append(_md_row(['Updated At',  _fmt_dt(opp.get('updated_at'))]))
    out.append('')

    if products:
        out.append('### Products')
        out.append('')
        out.append(_md_header(['Product', 'Quantity', 'Unit Price', 'Discount', 'Line Total']))
        total_products = 0.0
        for p in products:
            lt = _safe_num(p.get('line_total'))
            total_products += lt
            out.append(_md_row([
                p.get('product_name') or 'N/A',
                p.get('quantity') or 0,
                _fmt_currency(p.get('unit_price', 0)),
                f"{p.get('discount', 0)}%",
                f'**{_fmt_currency(lt)}**',
            ]))
        out.append('')
        out.append(f'**Total Product Value:** {_fmt_currency(total_products)}')
        out.append('')

    if stage_history:
        out.append('### Stage History')
        out.append('')
        out.append(_md_header(['Stage', 'Changed At']))
        for h in stage_history:
            out.append(_md_row([h.get('stage') or 'N/A', _fmt_dt(h.get('changed_at'))]))
        out.append('')


# ── Contact detail renderer (create/update modes that return a contact) ───────

def _render_contact_detail(out: list, contact: dict, report_data: dict, meta_raw: dict, action_verb: str):
    out.append(f'**{action_verb} Contact: {contact.get("full_name") or "Untitled Contact"}**')
    out.append('')
    out.append('### Contact Details')
    out.append(_md_header(['Field', 'Value']))
    for label, key, transform in [
        ('Contact ID',        'contact_id',         _trunc_uuid),
        ('Full Name',         'full_name',           None),
        ('First Name',        'first_name',          None),
        ('Last Name',         'last_name',           None),
        ('Email',             'email',               None),
        ('Phone',             'phone',               None),
        ('Role',              'role',                None),
        ('Status',            'status',              None),
        ('Is Customer',       'is_customer',         lambda v: 'Yes' if v else 'No'),
        ('Is Email Verified', 'is_email_verified',   lambda v: 'Yes' if v else 'No'),
        ('Account Name',      'account_name',        None),
        ('Account ID',        'account_id',          _trunc_uuid),
        ('Owner ID',          'owner_id',            _trunc_uuid),
        ('Created At',        'created_at',          _fmt_dt),
        ('Created By',        'created_by',          _trunc_uuid),
        ('Updated At',        'updated_at',          _fmt_dt),
        ('Updated By',        'updated_by',          _trunc_uuid),
        ('Is Deleted',        'is_deleted',          lambda v: 'Yes' if v else 'No'),
    ]:
        raw = contact.get(key)
        val = transform(raw) if transform else (raw or 'N/A')
        out.append(_md_row([label, val]))
    out.append('')

    # Addresses
    if report_data.get('addresses'):
        out.append('### All Addresses')
        out.append('')
        out.append(_md_header(['Label', 'Street', 'Line2', 'City', 'Province', 'Postal Code', 'Country', 'Is Default', 'Address ID']))
        for addr in report_data['addresses']:
            out.append(_md_row([
                addr.get('label') or 'N/A', addr.get('street') or 'N/A',
                addr.get('line2') or 'N/A',  addr.get('city') or 'N/A',
                addr.get('province') or 'N/A', addr.get('postal_code') or 'N/A',
                addr.get('country') or 'N/A', 'Yes' if addr.get('is_default') else 'No',
                _trunc_uuid(addr.get('address_id')),
            ]))
        out.append('')

    for section, key, label in [
        ('Billing Address', 'billingAddress', 'Billing'),
        ('Shipping Address', 'shippingAddress', 'Shipping'),
    ]:
        addr = report_data.get(key, {})
        if addr:
            out.append(f'### {section}')
            out.append('')
            out.append(_md_header(['Field', 'Value']))
            for f_label, f_key in [
                ('Label', 'label'), ('Street', 'street'), ('Line2', 'line2'),
                ('City', 'city'), ('Province', 'province'), ('Postal Code', 'postal_code'),
                ('Country', 'country'), ('Is Default', 'is_default'), ('Address ID', 'address_id'),
            ]:
                v = addr.get(f_key)
                if f_key == 'is_default':
                    v = 'Yes' if v else 'No'
                elif f_key == 'address_id':
                    v = _trunc_uuid(v)
                out.append(_md_row([f_label, v or 'N/A']))
            out.append('')

    if report_data.get('opportunities'):
        out.append('### Opportunities')
        out.append('')
        out.append(_md_header(['Name', 'Stage', 'Amount', 'Status', 'Opportunity ID']))
        for opp in report_data['opportunities']:
            out.append(_md_row([
                opp.get('name') or 'N/A', opp.get('stage') or 'N/A',
                _fmt_currency(opp.get('amount', 0)), opp.get('status') or 'N/A',
                _trunc_uuid(opp.get('opportunity_id')),
            ]))
        out.append('')

    if report_data.get('cases'):
        out.append('### Cases')
        out.append('')
        out.append(_md_header(['Case ID', 'Subject', 'Status', 'Created At']))
        for c in report_data['cases']:
            out.append(_md_row([
                _trunc_uuid(c.get('case_id')), c.get('subject') or 'N/A',
                c.get('status') or 'N/A', _fmt_dt(c.get('created_at')),
            ]))
        out.append('')

    if report_data.get('activities'):
        out.append('### Recent Activities')
        out.append('')
        out.append(_md_header(['Type', 'Subject', 'Created At', 'Activity ID']))
        for act in report_data['activities']:
            out.append(_md_row([
                act.get('type') or 'N/A', act.get('subject') or 'N/A',
                _fmt_dt(act.get('created_at')), _trunc_uuid(act.get('activity_id')),
            ]))
        out.append('')


# ── Subtable helper for multi-dimension reports ───────────────────────────────

def _render_breakdown_table(out: list, title: str, data: list, name_col: str, name_label: str, extra_cols: list = None):
    """
    Render a 6-column breakdown table (name, count, amount, weighted, margin$, w-margin$)
    with a running totals footer row.
    """
    if not data:
        return
    out.append(f'#### {title}')
    out.append('')
    out.append(_md_header([name_label, 'Count', 'Amount', 'Weighted Amount', 'Margin Dollars', 'Weighted Margin']))
    totals = {'cnt': 0, 'amt': 0.0, 'w_amt': 0.0, 'margin': 0.0, 'w_margin': 0.0}
    for r in data:
        cnt    = _safe_num(r.get('opportunity_count'))
        amt    = _safe_num(r.get('amount'))
        w_amt  = _safe_num(r.get('weighted_amount'))
        margin = _safe_num(r.get('margin_dollars'))
        w_mrg  = _safe_num(r.get('weighted_margin_dollars'))
        totals['cnt']    += cnt
        totals['amt']    += amt
        totals['w_amt']  += w_amt
        totals['margin'] += margin
        totals['w_margin'] += w_mrg
        label = r.get(name_col) or 'N/A'
        out.append(_md_row([label, int(cnt), _fmt_currency(amt), _fmt_currency(w_amt), _fmt_currency(margin), _fmt_currency(w_mrg)]))
    out.append(_md_row(['**Total**', int(totals['cnt']), _fmt_currency(totals['amt']), _fmt_currency(totals['w_amt']), _fmt_currency(totals['margin']), _fmt_currency(totals['w_margin'])]))
    out.append('')


# ============================================================================
# PUBLIC API
# ============================================================================

def format_response(db_rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format sp_opportunities DB rows into the output dict expected by main.py.

    Returns
    -------
    dict with keys:
      output        — formatted markdown string
      mode          — SP mode string
      report_mode   — internal report mode identifier
      search_results— list (for search modes, consumed by HTML typeahead)
      product_lines — list (for get mode, consumed by HTML update-product form)
      owners        — list (for get_owners mode)
    """
    mode = str(params.get('mode') or 'unknown').lower().strip()
    response = _parse_response(db_rows)
    metadata_raw = response.get('metadata', {}) or {}
    meta_status = metadata_raw.get('status', 'success')
    meta_code   = metadata_raw.get('code', 0)
    meta_msg    = metadata_raw.get('message', '')

    logger.info(f'Format Response (sp_opportunities v3.3) — mode={mode}')

    # ── Error short-circuit ───────────────────────────────────────────────────
    is_error   = (meta_status == 'error' or (isinstance(meta_code, (int, float)) and meta_code < 0))
    is_warning = (meta_status == 'warning' or meta_code == 100)

    if is_error:
        output = (
            f'### ERROR\n'
            f'**Time:** {_fmt_dt(datetime.utcnow().isoformat())}\n'
            f'**Error Code:** {meta_code}\n'
            f'**Error Message:** {meta_msg}\n\n'
            f'Please fix the input and try again.'
        )
        return {'output': output, 'mode': mode, 'report_mode': 'error'}

    # ── Mode routing ──────────────────────────────────────────────────────────
    report_mode  = 'generic'
    report_data: Dict[str, Any] = {}
    opportunities: list = []
    opportunity: Optional[dict] = None
    contact: Optional[dict] = None

    if mode == 'list':
        report_mode    = 'opportunity_list'
        opportunities  = response.get('opportunities') or []
        report_data['pagination'] = {
            'page':         metadata_raw.get('page', 1),
            'pageSize':     metadata_raw.get('page_size', 50),
            'totalRecords': metadata_raw.get('total_records', len(opportunities)),
            'totalPages':   metadata_raw.get('total_pages', 1),
            'totalAmount':  metadata_raw.get('total_amount', 0),
        }

    elif mode == 'get':
        report_mode  = 'opportunity_detail'
        opportunity  = response.get('opportunity')
        report_data['products']     = response.get('products') or []
        report_data['stageHistory'] = response.get('stage_history') or []

    elif mode == 'create':
        if response.get('contact'):
            report_mode = 'contact_created'
            contact     = response['contact']
            report_data.update({
                'contact':        contact,
                'contactId':      contact.get('contact_id'),
                'opportunities':  contact.get('opportunities') or [],
                'addresses':      contact.get('all_addresses') or [],
                'billingAddress': contact.get('billing_address') or {},
                'shippingAddress':contact.get('shipping_address') or {},
                'activities':     contact.get('recent_activities') or [],
                'cases':          contact.get('cases') or [],
            })
        else:
            report_mode = 'opportunity_created'
            opportunity = response.get('opportunity')
            report_data['opportunityId'] = (
                response.get('opportunity_id')
                or (opportunity or {}).get('opportunity_id')
            )
            report_data['products']     = response.get('products') or []
            report_data['stageHistory'] = response.get('stage_history') or []

    elif mode == 'update':
        if response.get('contact'):
            report_mode = 'contact_updated'
            contact     = response['contact']
            report_data.update({
                'contact':        contact,
                'opportunities':  contact.get('opportunities') or [],
                'addresses':      contact.get('all_addresses') or [],
                'billingAddress': contact.get('billing_address') or {},
                'shippingAddress':contact.get('shipping_address') or {},
                'activities':     contact.get('recent_activities') or [],
                'cases':          contact.get('cases') or [],
            })
        else:
            report_mode = 'opportunity_updated'
            opportunity = response.get('opportunity')
            report_data['products']     = response.get('products') or []
            report_data['stageHistory'] = response.get('stage_history') or []

    elif mode == 'change_stage':
        report_mode = 'stage_changed'
        report_data['fromStage'] = response.get('from_stage')
        report_data['toStage']   = response.get('to_stage')

    elif mode == 'close_won':    report_mode = 'closed_won'
    elif mode == 'close_lost':   report_mode = 'closed_lost'
    elif mode == 'delete':       report_mode = 'deleted'

    elif mode == 'add_product':
        report_mode = 'product_added'
        report_data['oppProduct']  = response.get('opp_product') or {}
        report_data['opportunity'] = response.get('opportunity') or {}

    elif mode == 'update_product':
        report_mode = 'product_updated'
        report_data['oppProduct']  = response.get('opp_product') or {}
        report_data['opportunity'] = response.get('opportunity') or {}

    elif mode == 'remove_product':
        report_mode = 'product_removed'

    elif mode == 'pipeline':
        report_mode = 'pipeline'
        report_data['pipeline'] = {
            'summary':              response.get('summary') or {},
            'by_stage':             response.get('by_stage') or [],
            'by_owner':             response.get('by_owner') or [],
            'by_lead_source':       response.get('by_lead_source') or [],
            'by_horizon':           response.get('by_horizon') or [],
            'by_product':           response.get('by_product') or [],
            'by_account':           response.get('by_account') or [],
            'margin_health_rollup': response.get('margin_health_rollup') or [],
        }

    elif mode == 'forecast':
        report_mode = 'forecast'
        report_data['forecast'] = {
            'summary':              response.get('summary') or {},
            'by_owner':             response.get('by_owner') or [],
            'by_lead_source':       response.get('by_lead_source') or [],
            'by_month_lead_source': response.get('by_month_lead_source') or [],
            'top_products':         response.get('top_products') or [],
            'top_accounts':         response.get('top_accounts') or [],
        }

    elif mode == 'search_accounts':
        report_mode = 'search_accounts'
        report_data['searchResults'] = response.get('accounts') or []

    elif mode == 'search_products':
        report_mode = 'search_products'
        report_data['searchResults'] = response.get('products') or []

    elif mode == 'search_opportunities':
        report_mode = 'search_opportunities'
        report_data['searchResults'] = response.get('opportunities') or []

    elif mode == 'get_owners':
        report_mode = 'get_owners'
        report_data['owners'] = response.get('owners') or []

    # =========================================================================
    # OUTPUT BUILDING
    # =========================================================================

    out: List[str] = []
    title = _mode_name(mode)
    if report_mode == 'contact_created': title = 'Contact Created'
    if report_mode == 'contact_updated': title = 'Contact Updated'

    out.append(f'### {title}')
    out.append(f'**Time:** {_fmt_dt(datetime.utcnow().isoformat())}')
    out.append('')

    # ── Opportunity List ──────────────────────────────────────────────────────
    if report_mode == 'opportunity_list':
        pg = report_data['pagination']
        out.append(
            f'**Page:** {pg["page"]} of {pg["totalPages"]} | '
            f'**Total:** {pg["totalRecords"]} opportunities | '
            f'**Pipeline Value:** {_fmt_currency(pg["totalAmount"])}'
        )
        out.append('')

        if not opportunities:
            out.append('**No opportunities found matching your criteria.**')
            out.append('')
        else:
            out.append(_md_header([
                'Opportunity', 'Stage', 'Probability', 'Amount', 'Weighted',
                'Account', 'Contact', 'Lead Source', 'Owner', 'Close Date', 'Opportunity ID',
            ]))
            for opp in opportunities:
                stage = opp.get('stage') or ''
                status = opp.get('status') or ''
                status_badge = '✓ WON' if status == 'closed_won' else ('✗ LOST' if status == 'closed_lost' else 'OPEN')
                weighted = _safe_num(opp.get('amount')) * _safe_num(opp.get('probability')) / 100
                out.append(_md_row([
                    f'{opp.get("name") or "Untitled"} ({status_badge})',
                    f'{_stage_icon(stage)} {stage or "N/A"}',
                    f'{opp.get("probability", 0)}%',
                    _fmt_currency(opp.get('amount', 0)),
                    _fmt_currency(weighted),
                    opp.get('account_name') or '—',
                    opp.get('contact_name') or '—',
                    opp.get('lead_source')  or '—',
                    opp.get('owner_name')   or '—',
                    _fmt_date(opp.get('close_date')),
                    opp.get('opportunity_id') or 'N/A',
                ]))
            out.append('')

    # ── Opportunity Detail ────────────────────────────────────────────────────
    elif report_mode == 'opportunity_detail' and opportunity:
        _render_opportunity_detail(out, opportunity, report_data.get('products', []), report_data.get('stageHistory', []))

    # ── Contact Detail (create/update returning a contact) ───────────────────
    elif report_mode in ('contact_created', 'contact_updated') and report_data.get('contact'):
        verb = 'Created' if report_mode == 'contact_created' else 'Updated'
        _render_contact_detail(out, report_data['contact'], report_data, metadata_raw, verb)

    # ── Opportunity Created ───────────────────────────────────────────────────
    elif report_mode == 'opportunity_created':
        out.append('**Opportunity Created Successfully!**')
        out.append('')
        if opportunity:
            _render_opportunity_detail(out, opportunity, report_data.get('products', []), report_data.get('stageHistory', []))
        else:
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Opportunity ID', _trunc_uuid(report_data.get('opportunityId'))]))
            out.append(_md_row(['Message', meta_msg or 'Opportunity created']))
            out.append('')

    # ── Opportunity Updated ───────────────────────────────────────────────────
    elif report_mode == 'opportunity_updated':
        out.append('**Opportunity Updated Successfully!**')
        out.append('')
        if opportunity:
            _render_opportunity_detail(out, opportunity, report_data.get('products', []), report_data.get('stageHistory', []))
        else:
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Message', meta_msg or 'Opportunity updated']))
            out.append('')

    # ── Stage Changed ─────────────────────────────────────────────────────────
    elif report_mode == 'stage_changed':
        if is_warning:
            out.append('⚠️ **Warning**')
            out.append('')
            out.append(meta_msg or 'Already at this stage')
            out.append('')
        else:
            out.append('**Stage Changed Successfully!**')
            out.append('')
            out.append(_md_header(['From Stage', 'To Stage']))
            out.append(_md_row([report_data.get('fromStage') or 'N/A', report_data.get('toStage') or 'N/A']))
            out.append('')

    # ── Closed Won / Lost / Deleted ───────────────────────────────────────────
    elif report_mode == 'closed_won':
        out.append('🎉 **Opportunity Closed as WON!**')
        out.append('')
        out.append('_Stage updated to **closed_won**, probability set to **100%**, status updated._')
        out.append('')

    elif report_mode == 'closed_lost':
        out.append('📉 **Opportunity Marked as LOST**')
        out.append('')
        out.append('_Stage updated to **closed_lost**, probability set to **0%**, status updated._')
        out.append('')

    elif report_mode == 'deleted':
        out.append('🗑️ **Opportunity Deleted**')
        out.append('')
        out.append('_Status updated to **deleted**._')
        out.append('')

    # ── Product Added ─────────────────────────────────────────────────────────
    elif report_mode == 'product_added':
        out.append('**Product Added Successfully!**')
        out.append('')
        op = report_data.get('oppProduct') or {}
        if op:
            out.append('### Added Product Line')
            out.append('')
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Opp Product ID',  _trunc_uuid(op.get('opp_product_id'))]))
            out.append(_md_row(['Product ID',      _trunc_uuid(op.get('product_id'))]))
            out.append(_md_row(['Quantity',         op.get('quantity', 0)]))
            out.append(_md_row(['Selling Price',    _fmt_currency(op.get('selling_price', 0))]))
            out.append(_md_row(['Discount',         f"{op.get('discount', 0)}%"]))
            out.append(_md_row(['Retail Price',     _fmt_currency(op.get('retail_price', 0))]))
            out.append(_md_row(['Wholesale Price',  _fmt_currency(op.get('wholesale_price', 0))]))
            out.append(_md_row(['Margin',           _fmt_currency(op.get('margin', 0))]))
            out.append(_md_row(['Margin %',         _fmt_pct(op.get('margin_pct', 0))]))
            out.append(_md_row(['Margin Health',    op.get('margin_health') or 'N/A']))
            out.append('')
        upd_opp = report_data.get('opportunity') or {}
        if upd_opp:
            out.append('### Updated Opportunity')
            out.append('')
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Opportunity ID', _trunc_uuid(upd_opp.get('opportunity_id'))]))
            out.append(_md_row(['Amount',         _fmt_currency(upd_opp.get('amount', 0))]))
            out.append(_md_row(['Total Margin',   _fmt_currency(upd_opp.get('total_margin', 0))]))
            out.append(_md_row(['Margin %',       _fmt_pct(upd_opp.get('margin_pct', 0))]))
            out.append(_md_row(['Margin Health',  upd_opp.get('margin_health') or 'N/A']))
            out.append('')
        out.append('_Opportunity total amount has been recalculated._')
        out.append('')

    # ── Product Updated ───────────────────────────────────────────────────────
    elif report_mode == 'product_updated':
        out.append('**Product Updated Successfully!**')
        out.append('')
        op = report_data.get('oppProduct') or {}
        if op.get('opp_product_id'):
            out.append('### Updated Product Line')
            out.append('')
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Opp Product ID',  _trunc_uuid(op.get('opp_product_id'))]))
            out.append(_md_row(['Product ID',      _trunc_uuid(op.get('product_id'))]))
            out.append(_md_row(['Quantity',         op.get('quantity', 0)]))
            out.append(_md_row(['Selling Price',    _fmt_currency(op.get('selling_price', 0))]))
            out.append(_md_row(['Discount',         f"{op.get('discount', 0)}%"]))
            out.append(_md_row(['Retail Price',     _fmt_currency(op.get('retail_price', 0))]))
            out.append(_md_row(['Wholesale Price',  _fmt_currency(op.get('wholesale_price', 0))]))
            out.append(_md_row(['Margin',           _fmt_currency(op.get('margin', 0))]))
            out.append(_md_row(['Margin %',         _fmt_pct(op.get('margin_pct', 0))]))
            out.append(_md_row(['Margin Health',    op.get('margin_health') or 'N/A']))
            out.append('')
        upd_opp = report_data.get('opportunity') or {}
        if upd_opp.get('opportunity_id'):
            out.append('### Updated Opportunity')
            out.append('')
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Opportunity ID', _trunc_uuid(upd_opp.get('opportunity_id'))]))
            out.append(_md_row(['Amount',         _fmt_currency(upd_opp.get('amount', 0))]))
            out.append(_md_row(['Total Margin',   _fmt_currency(upd_opp.get('total_margin', 0))]))
            out.append(_md_row(['Margin %',       _fmt_pct(upd_opp.get('margin_pct', 0))]))
            out.append(_md_row(['Margin Health',  upd_opp.get('margin_health') or 'N/A']))
            out.append('')
        if not op.get('opp_product_id') and not upd_opp.get('opportunity_id'):
            out.append(_md_header(['Field', 'Value']))
            out.append(_md_row(['Message', meta_msg or 'Product updated']))
            out.append('')
        out.append('_Opportunity total amount has been recalculated._')
        out.append('')

    # ── Product Removed ───────────────────────────────────────────────────────
    elif report_mode == 'product_removed':
        out.append('**Product Removed Successfully!**')
        out.append('')
        out.append(_md_header(['Field', 'Value']))
        out.append(_md_row(['Message', meta_msg or 'Product removed']))
        out.append('')
        out.append('_Opportunity total amount has been recalculated._')
        out.append('')

    # ── Pipeline ──────────────────────────────────────────────────────────────
    elif report_mode == 'pipeline' and report_data.get('pipeline'):
        pl = report_data['pipeline']
        s  = pl.get('summary') or {}

        out.append('#### Key Metrics')
        out.append('')
        out.append(_md_header(['Metric', 'Value']))
        out.append(_md_row(['Opportunities',          s.get('opportunity_count', 0)]))
        out.append(_md_row(['Total Amount',           _fmt_currency(s.get('amount', 0))]))
        out.append(_md_row(['Weighted Amount',         _fmt_currency(s.get('weighted_amount', 0))]))
        out.append(_md_row(['Margin Dollars',          _fmt_currency(s.get('margin_dollars', 0))]))
        out.append(_md_row(['Weighted Margin Dollars', _fmt_currency(s.get('weighted_margin_dollars', 0))]))
        out.append('')

        # by_stage — has stage icon prefix
        if pl.get('by_stage'):
            out.append('#### Pipeline by Stage')
            out.append('')
            out.append(_md_header(['Stage', 'Count', 'Amount', 'Weighted Amount', 'Margin Dollars', 'Weighted Margin']))
            totals = {'cnt': 0.0, 'amt': 0.0, 'w': 0.0, 'm': 0.0, 'wm': 0.0}
            for r in pl['by_stage']:
                cnt   = _safe_num(r.get('opportunity_count'))
                amt   = _safe_num(r.get('amount'))
                w     = _safe_num(r.get('weighted_amount'))
                m     = _safe_num(r.get('margin_dollars'))
                wm    = _safe_num(r.get('weighted_margin_dollars'))
                for k, v in [('cnt', cnt), ('amt', amt), ('w', w), ('m', m), ('wm', wm)]:
                    totals[k] += v
                stage = r.get('stage') or 'N/A'
                out.append(_md_row([f'{_stage_icon(stage)} {stage}', int(cnt), _fmt_currency(amt), _fmt_currency(w), _fmt_currency(m), _fmt_currency(wm)]))
            out.append(_md_row(['**Total**', int(totals['cnt']), _fmt_currency(totals['amt']), _fmt_currency(totals['w']), _fmt_currency(totals['m']), _fmt_currency(totals['wm'])]))
            out.append('')

        _render_breakdown_table(out, 'Pipeline by Owner',       pl.get('by_owner', []),       'owner_name',  'Owner')
        _render_breakdown_table(out, 'Pipeline by Lead Source', pl.get('by_lead_source', []), 'lead_source', 'Lead Source')

        if pl.get('by_horizon'):
            out.append('#### Pipeline by Close Horizon')
            out.append('')
            out.append(_md_header(['Horizon', 'Count', 'Amount', 'Weighted Amount', 'Margin Dollars', 'Weighted Margin']))
            for r in pl['by_horizon']:
                out.append(_md_row([
                    r.get('horizon_bucket') or 'N/A', int(_safe_num(r.get('opportunity_count'))),
                    _fmt_currency(r.get('amount', 0)), _fmt_currency(r.get('weighted_amount', 0)),
                    _fmt_currency(r.get('margin_dollars', 0)), _fmt_currency(r.get('weighted_margin_dollars', 0)),
                ]))
            out.append('')

        _render_breakdown_table(out, 'Pipeline by Product', pl.get('by_product', []), 'product_name', 'Product')
        _render_breakdown_table(out, 'Pipeline by Account', pl.get('by_account', []), 'account_name', 'Account')

        if pl.get('margin_health_rollup'):
            out.append('#### Margin Health Rollup')
            out.append('')
            out.append(_md_header(['Margin Health', 'Margin Dollars']))
            total_health = 0.0
            for r in pl['margin_health_rollup']:
                m = _safe_num(r.get('margin_dollars'))
                total_health += m
                h = r.get('margin_health') or 'N/A'
                out.append(_md_row([f'{_health_icon(h)} {h}', _fmt_currency(m)]))
            out.append(_md_row(['**Total**', _fmt_currency(total_health)]))
            out.append('')

    # ── Forecast ──────────────────────────────────────────────────────────────
    elif report_mode == 'forecast' and report_data.get('forecast'):
        fc = report_data['forecast']
        fs = fc.get('summary')
        if isinstance(fs, list):
            fs = fs[0] if fs else {}
        fs = fs or {}

        out.append('#### Key Metrics')
        out.append('')
        out.append(_md_header(['Metric', 'Value']))
        out.append(_md_row(['Historical Revenue',          _fmt_currency(fs.get('historical_revenue', 0))]))
        out.append(_md_row(['Forecast Revenue',             _fmt_currency(fs.get('forecast_revenue', 0))]))
        out.append(_md_row(['Historical Margin Dollars',    _fmt_currency(fs.get('historical_margin_dollars', 0))]))
        out.append(_md_row(['Forecast Margin Dollars',      _fmt_currency(fs.get('forecast_margin_dollars', 0))]))
        out.append('')

        # Helper: 6-col forecast table with totals
        def _fc_table(title: str, data: list, name_col: str, name_label: str, show_id: bool = False, id_col: str = ''):
            if not data:
                return
            out.append(f'#### {title}')
            out.append('')
            cols = [name_label]
            if show_id:
                cols.append(name_label.replace(' Name', ' ID'))
            cols += ['Historical Revenue', 'Forecast Revenue', 'Historical Margin Dollars', 'Forecast Margin Dollars']
            out.append(_md_header(cols))
            totals = {'hr': 0.0, 'fr': 0.0, 'hm': 0.0, 'fm': 0.0}
            for r in _sort_desc_by_revenue(data):
                hr = _safe_num(r.get('historical_revenue'))
                fr = _safe_num(r.get('forecast_revenue'))
                hm = _safe_num(r.get('historical_margin_dollars'))
                fm = _safe_num(r.get('forecast_margin_dollars'))
                for k, v in [('hr', hr), ('fr', fr), ('hm', hm), ('fm', fm)]:
                    totals[k] += v
                row = [r.get(name_col) or 'N/A']
                if show_id:
                    row.append(_trunc_uuid(r.get(id_col)))
                row += [_fmt_currency(hr), _fmt_currency(fr), _fmt_currency(hm), _fmt_currency(fm)]
                out.append(_md_row(row))
            total_row = ['**Total**']
            if show_id:
                total_row.append('')
            total_row += [_fmt_currency(totals['hr']), _fmt_currency(totals['fr']), _fmt_currency(totals['hm']), _fmt_currency(totals['fm'])]
            out.append(_md_row(total_row))
            out.append('')

        _fc_table('Forecast by Owner',       fc.get('by_owner', []),       'owner_name',   'Owner Name',   show_id=True, id_col='owner_id')
        _fc_table('Top Accounts',             fc.get('top_accounts', []),   'account_name', 'Account Name', show_id=True, id_col='account_id')
        _fc_table('Top Products',             fc.get('top_products', []),   'product_name', 'Product Name', show_id=True, id_col='product_id')
        _fc_table('Forecast by Lead Source (Aggregated over Months)', fc.get('by_lead_source', []), 'lead_source', 'Lead Source')

        # by_month_lead_source — aggregate by month
        by_month = fc.get('by_month_lead_source') or []
        if by_month:
            out.append('#### Forecast by Month (Aggregated over Lead Sources)')
            out.append('')
            out.append(_md_header(['Month', 'Historical Revenue', 'Forecast Revenue', 'Historical Margin Dollars', 'Forecast Margin Dollars']))
            month_map: Dict[str, dict] = {}
            for row in by_month:
                m = row.get('month') or '?'
                if m not in month_map:
                    month_map[m] = {'hr': 0.0, 'fr': 0.0, 'hm': 0.0, 'fm': 0.0}
                month_map[m]['hr'] += _safe_num(row.get('historical_revenue'))
                month_map[m]['fr'] += _safe_num(row.get('forecast_revenue'))
                month_map[m]['hm'] += _safe_num(row.get('historical_margin_dollars'))
                month_map[m]['fm'] += _safe_num(row.get('forecast_margin_dollars'))
            sorted_months = sorted(
                (k for k, v in month_map.items() if any(v[x] > 0 for x in ('hr', 'fr', 'hm', 'fm'))),
                reverse=True,
            )
            totals_m = {'hr': 0.0, 'fr': 0.0, 'hm': 0.0, 'fm': 0.0}
            for m in sorted_months:
                r = month_map[m]
                for k in totals_m:
                    totals_m[k] += r[k]
                out.append(_md_row([m, _fmt_currency(r['hr']), _fmt_currency(r['fr']), _fmt_currency(r['hm']), _fmt_currency(r['fm'])]))
            out.append(_md_row(['**Total**', _fmt_currency(totals_m['hr']), _fmt_currency(totals_m['fr']), _fmt_currency(totals_m['hm']), _fmt_currency(totals_m['fm'])]))
            out.append('')

    # ── Search: Accounts ──────────────────────────────────────────────────────
    elif report_mode == 'search_accounts':
        accounts = report_data.get('searchResults') or []
        query    = metadata_raw.get('query') or ''
        qsuffix  = f' matching "{query}"' if query else ''
        if not accounts:
            out.append(f'_No accounts found{qsuffix}._')
        else:
            cnt = len(accounts)
            out.append(f'**Found {cnt} account{"s" if cnt != 1 else ""}{qsuffix}:**')
            out.append('')
            out.append(_md_header(['Account Name', 'Type', 'Industry', 'Status']))
            for a in accounts:
                out.append(_md_row([a.get('account_name') or '—', a.get('type') or '—', a.get('industry') or '—', a.get('status') or '—']))
            out.append('')

    # ── Search: Products ──────────────────────────────────────────────────────
    elif report_mode == 'search_products':
        products = report_data.get('searchResults') or []
        query    = metadata_raw.get('query') or ''
        qsuffix  = f' matching "{query}"' if query else ''
        if not products:
            out.append(f'_No products found{qsuffix}._')
        else:
            cnt = len(products)
            out.append(f'**Found {cnt} product{"s" if cnt != 1 else ""}{qsuffix}:**')
            out.append('')
            out.append(_md_header(['Product Name', 'SKU', 'Retail Price', 'Wholesale Price', 'Stock']))
            for p in products:
                out.append(_md_row([
                    p.get('product_name') or '—', p.get('sku') or '—',
                    _fmt_currency(p['retail_price'])     if p.get('retail_price')    is not None else '—',
                    _fmt_currency(p['wholesale_price'])  if p.get('wholesale_price') is not None else '—',
                    str(p['stock_quantity'])              if p.get('stock_quantity')  is not None else '—',
                ]))
            out.append('')

    # ── Search: Opportunities ─────────────────────────────────────────────────
    elif report_mode == 'search_opportunities':
        opps  = report_data.get('searchResults') or []
        query = metadata_raw.get('query') or ''
        qsuffix = f' matching "{query}"' if query else ''
        if not opps:
            out.append(f'_No opportunities found{qsuffix}._')
        else:
            cnt = len(opps)
            out.append(f'**Found {cnt} opportunit{"ies" if cnt != 1 else "y"}{qsuffix}:**')
            out.append('')
            out.append(_md_header(['Opportunity', 'Account', 'Stage', 'Amount', 'Status']))
            for o in opps:
                out.append(_md_row([
                    o.get('opportunity_name') or '—', o.get('account_name') or '—',
                    o.get('stage') or '—',
                    _fmt_currency(o['amount']) if o.get('amount') is not None else '—',
                    o.get('status') or '—',
                ]))
            out.append('')

    # ── Get Owners ────────────────────────────────────────────────────────────
    elif report_mode == 'get_owners':
        out.append('_Owner list loaded._')

    # ── Generic fallback ──────────────────────────────────────────────────────
    else:
        out.append('**Operation Completed**')
        out.append('')
        out.append(_md_header(['Field', 'Value']))
        out.append(_md_row(['Status',  meta_status]))
        out.append(_md_row(['Code',    meta_code]))
        out.append(_md_row(['Message', meta_msg or 'N/A']))
        out.append('')

    # =========================================================================
    # BUILD RETURN DICT (mirrors n8n returnPayload)
    # =========================================================================
    result: Dict[str, Any] = {
        'output':      '\n'.join(out),
        'mode':        mode,
        'report_mode': report_mode,
    }

    # Raw arrays consumed by the HTML frontend without markdown parsing
    if report_mode in ('search_accounts', 'search_products', 'search_opportunities'):
        result['search_results'] = report_data.get('searchResults') or []
        result['search_query']   = metadata_raw.get('query') or ''
        result['search_mode']    = mode

    if report_mode == 'opportunity_detail':
        result['product_lines'] = report_data.get('products') or []

    if report_mode == 'get_owners':
        result['owners'] = report_data.get('owners') or []

    return result
