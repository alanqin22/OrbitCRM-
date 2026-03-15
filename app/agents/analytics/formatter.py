"""Response formatter for Analytics Dashboard v3.1.

CHANGELOG v3.1
  - Replaced owner_id with owner_name + owner_role in:
    • Owner Breakdown table
    • AR Aging by Owner table
    • Activity Productivity table
  - All owner-related tables now show human-readable Name and Role columns.

Supported data sections (15):
  forecast_summary, ai_vs_human_forecast, owner_breakdown, period_trend,
  forecast_accuracy, open_pipeline_summary, booked_revenue,
  recent_invoiced_revenue, recent_cashflow, ar_aging, ar_aging_by_owner,
  ar_aging_by_account, ar_aging_by_product, lead_source_performance,
  activity_productivity.

Side-channel output (passed to ChatResponse):
  dashboardData   — raw dict keyed by section name (for HTML chart rendering)
  summaryMetrics  — computed KPIs dict (for KPI card widgets)
  params          — echoed SP params (for display and re-query)
  meta            — generation timestamp + record counts per section

Result key from SP:  'sp_analytics_dashboard'  (no explicit alias in SQL)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_date(value) -> str:
    if not value:
        return 'N/A'
    try:
        if isinstance(value, (datetime, date)):
            return value.strftime('%b %d, %Y')
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.strftime('%b %d, %Y')
    except (ValueError, AttributeError):
        return str(value) or 'N/A'


def _fmt_currency(value, currency: str = 'USD') -> str:
    if value is None:
        return '$0.00'
    try:
        num = float(value)
        return f'${num:,.2f}'
    except (TypeError, ValueError):
        return '$0.00'


def _fmt_number(value) -> str:
    if value is None:
        return '0'
    try:
        return f'{int(value):,}'
    except (TypeError, ValueError):
        return '0'


def _fmt_pct(value) -> str:
    if value is None:
        return '0.00%'
    try:
        return f'{float(value):.2f}%'
    except (TypeError, ValueError):
        return '0.00%'


def _fmt_uuid_short(value) -> str:
    if not value:
        return 'N/A'
    s = str(value)
    return s[:8] + '...' if len(s) > 8 else s


def _safe_arr(v) -> list:
    return v if isinstance(v, list) else []


def _sum_field(arr: list, field: str) -> float:
    return sum(float(row.get(field) or 0) for row in _safe_arr(arr))


def _count_field(arr: list, field: str) -> int:
    return sum(int(row.get(field) or 0) for row in _safe_arr(arr))


def _parse_response(db_rows: List[Dict]) -> Dict:
    """
    Extract the SP response from database rows.
    sp_analytics_dashboard has no explicit alias in the SQL, so psycopg2
    returns data under 'sp_analytics_dashboard'. Also checks 'result' as
    a fallback for any middleware that renames the column.
    """
    if not db_rows:
        return {}
    first = db_rows[0]
    for key in ('sp_analytics_dashboard', 'result'):
        val = first.get(key)
        if val is not None:
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    return parsed
                except json.JSONDecodeError:
                    pass
            elif isinstance(val, dict):
                return val
    # Fallback: treat the row itself as the response
    return first


# ============================================================================
# TABLE BUILDER
# ============================================================================

_FORMATTERS = {
    'currency':   _fmt_currency,
    'percentage': _fmt_pct,
    'number':     _fmt_number,
    'uuid':       _fmt_uuid_short,
}


def _add_table(out: List[str], title: str, icon: str, data: list, columns: list) -> None:
    """Append a markdown table section to `out`."""
    out.append(f'**{icon} {title}**')
    out.append('')
    if not data:
        out.append('No data available.')
        out.append('')
        return

    header = '| ' + ' | '.join(c['label'] for c in columns) + ' |'
    sep    = '| ' + ' | '.join('---' for _ in columns) + ' |'
    out.append(header)
    out.append(sep)

    for row in data:
        cells = []
        for c in columns:
            v   = row.get(c['key'])
            fmt = c.get('format')
            if fmt and fmt in _FORMATTERS:
                cells.append(_FORMATTERS[fmt](v))
            else:
                cells.append(str(v) if v is not None else 'N/A')
        out.append('| ' + ' | '.join(cells) + ' |')

    out.append('')


# ============================================================================
# SUMMARY METRICS
# ============================================================================

def _compute_summary(d: dict) -> dict:
    sm: dict = {
        'totalPipelineAmount':        _sum_field(d.get('open_pipeline_summary'), 'total_amount'),
        'totalWeightedPipeline':      _sum_field(d.get('open_pipeline_summary'), 'weighted_amount'),
        'totalPipelineOpportunities': _count_field(d.get('open_pipeline_summary'), 'opportunity_count'),

        'totalForecastAmount':        _sum_field(d.get('forecast_summary'), 'forecast_amount'),
        'totalForecastPipeline':      _sum_field(d.get('forecast_summary'), 'total_amount'),
        'totalForecastOpportunities': _count_field(d.get('forecast_summary'), 'opportunity_count'),

        'totalBookedRevenue':         _sum_field(d.get('booked_revenue'), 'booked_revenue'),
        'totalDiscounts':             _sum_field(d.get('booked_revenue'), 'discount_total'),
        'totalLineItems':             _count_field(d.get('booked_revenue'), 'line_count'),

        'totalInvoiced':              _sum_field(d.get('recent_invoiced_revenue'), 'invoiced_amount'),
        'totalPaid':                  _sum_field(d.get('recent_invoiced_revenue'), 'paid_amount'),
        'totalOutstanding':           _sum_field(d.get('recent_invoiced_revenue'), 'outstanding_amount'),

        'totalAROutstanding':         _sum_field(d.get('ar_aging'), 'outstanding_amount'),
        'totalARInvoices':            _count_field(d.get('ar_aging'), 'invoice_count'),

        'totalARByOwner':             _sum_field(d.get('ar_aging_by_owner'), 'outstanding_amount'),
        'totalAROwnerInvoices':       _count_field(d.get('ar_aging_by_owner'), 'invoice_count'),

        'totalARByAccount':           _sum_field(d.get('ar_aging_by_account'), 'outstanding_amount'),
        'totalARAccountInvoices':     _count_field(d.get('ar_aging_by_account'), 'invoice_count'),

        'totalARByProduct':           _sum_field(d.get('ar_aging_by_product'), 'outstanding_amount'),
        'totalARProductInvoices':     _count_field(d.get('ar_aging_by_product'), 'invoice_count'),

        'totalCashReceived':          _sum_field(d.get('recent_cashflow'), 'paid_amount'),
        'totalPayments':              _count_field(d.get('recent_cashflow'), 'payment_count'),

        'totalActivities':            _count_field(d.get('activity_productivity'), 'activity_count'),
        'totalCompleted':             _count_field(d.get('activity_productivity'), 'completed_count'),
        'totalOverdue':               _count_field(d.get('activity_productivity'), 'overdue_count'),
    }

    sm['activityCompletionRate'] = (
        round((sm['totalCompleted'] / sm['totalActivities']) * 100, 1)
        if sm['totalActivities'] > 0 else 0
    )
    return sm


# ============================================================================
# PUBLIC API
# ============================================================================

def format_response(db_rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format sp_analytics_dashboard DB rows into the output dict expected by main.py.

    Returns dict with keys:
      output         — formatted markdown string
      mode           — 'dashboard'
      success        — bool
      dashboardData  — raw section dict (for HTML chart/table rendering)
      summaryMetrics — computed KPI dict (for KPI card widgets)
      params         — echoed SP param names (p_start_date etc.)
      meta           — generation time + record counts per section
    """
    response = _parse_response(db_rows)
    logger.info(f'Format Response (sp_analytics_dashboard v3.1) — keys: {list(response.keys())}')

    # ── Error check ───────────────────────────────────────────────────────────
    if not response or response.get('error'):
        error_msg = response.get('message') or 'Unknown error'
        error_code = response.get('code') or -999
        output = (
            f'### ❌ ERROR\n'
            f'**Time:** {_fmt_date(datetime.utcnow())}\n'
            f'**Error Code:** {error_code}\n'
            f'**Error Message:** {error_msg}\n\n'
            f'Please fix the input and try again.'
        )
        return {
            'output': output, 'mode': 'error', 'success': False,
            'dashboardData': {}, 'summaryMetrics': {}, 'params': {}, 'meta': {}
        }

    dashboard_data = response

    # ── Summary metrics ───────────────────────────────────────────────────────
    summary_metrics = _compute_summary(dashboard_data)

    # ── Echoed params (p_snake_case format matching n8n formatter) ────────────
    echoed_params = {
        'p_start_date':  params.get('startDate'),
        'p_end_date':    params.get('endDate'),
        'p_owner_id':    params.get('ownerId'),
        'p_account_id':  params.get('accountId'),
        'p_product_id':  params.get('productId'),
        'p_report_type': params.get('reportType'),
    }

    # ── Text output ───────────────────────────────────────────────────────────
    out: List[str] = []
    out.append('### 📊 Analytics Dashboard')
    out.append(f'**Time:** {_fmt_date(datetime.utcnow())}')
    out.append(
        f'**Date Range:** {_fmt_date(params.get("startDate"))} '
        f'to {_fmt_date(params.get("endDate"))}'
    )
    if params.get('ownerId'):   out.append(f'**Owner Filter:** {params["ownerId"]}')
    if params.get('accountId'): out.append(f'**Account Filter:** {params["accountId"]}')
    if params.get('productId'): out.append(f'**Product Filter:** {params["productId"]}')
    out.append('')

    # Key metrics summary card
    out.append('**📈 Key Metrics Summary**')
    out.append('')
    out.append('| Metric | Value |')
    out.append('| --- | --- |')
    out.append(f'| Total Pipeline | {_fmt_currency(summary_metrics["totalPipelineAmount"])} |')
    out.append(f'| Weighted Pipeline | {_fmt_currency(summary_metrics["totalWeightedPipeline"])} |')
    out.append(f'| Booked Revenue | {_fmt_currency(summary_metrics["totalBookedRevenue"])} |')
    out.append(f'| Cash Received | {_fmt_currency(summary_metrics["totalCashReceived"])} |')
    out.append(f'| AR Outstanding | {_fmt_currency(summary_metrics["totalAROutstanding"])} |')
    out.append(f'| Activity Completion | {summary_metrics["activityCompletionRate"]}% |')
    out.append('')

    # ── Section tables ────────────────────────────────────────────────────────

    _add_table(out, 'Forecast Summary', '🎯',
               _safe_arr(dashboard_data.get('forecast_summary')), [
                   {'key': 'period_key',        'label': 'Period'},
                   {'key': 'forecast_type',     'label': 'Type'},
                   {'key': 'total_amount',      'label': 'Total Amount',    'format': 'currency'},
                   {'key': 'forecast_amount',   'label': 'Forecast Amount', 'format': 'currency'},
                   {'key': 'opportunity_count', 'label': 'Opportunities',   'format': 'number'},
               ])

    _add_table(out, 'AI vs Human Forecast', '🤖',
               _safe_arr(dashboard_data.get('ai_vs_human_forecast')), [
                   {'key': 'period_key',      'label': 'Period'},
                   {'key': 'ai_forecast',     'label': 'AI Forecast',  'format': 'currency'},
                   {'key': 'human_commit',    'label': 'Human Commit', 'format': 'currency'},
                   {'key': 'human_best_case', 'label': 'Best Case',    'format': 'currency'},
               ])

    # Owner Breakdown — shows name + role (v3.1)
    _add_table(out, 'Owner Breakdown', '👥',
               _safe_arr(dashboard_data.get('owner_breakdown')), [
                   {'key': 'owner_name',       'label': 'Owner Name'},
                   {'key': 'owner_role',       'label': 'Role'},
                   {'key': 'forecast_type',    'label': 'Type'},
                   {'key': 'forecast_amount',  'label': 'Forecast Amount', 'format': 'currency'},
                   {'key': 'total_amount',     'label': 'Total Amount',    'format': 'currency'},
                   {'key': 'opportunity_count','label': 'Opportunities',   'format': 'number'},
               ])

    _add_table(out, 'Period Trend', '📈',
               _safe_arr(dashboard_data.get('period_trend')), [
                   {'key': 'period_key',      'label': 'Period'},
                   {'key': 'forecast_amount', 'label': 'Forecast Amount', 'format': 'currency'},
                   {'key': 'total_amount',    'label': 'Total Amount',    'format': 'currency'},
               ])

    _add_table(out, 'Forecast Accuracy', '🎯',
               _safe_arr(dashboard_data.get('forecast_accuracy')), [
                   {'key': 'period_key',        'label': 'Period'},
                   {'key': 'forecast_type',     'label': 'Type'},
                   {'key': 'avg_ai_confidence', 'label': 'Avg AI Confidence', 'format': 'percentage'},
                   {'key': 'snapshot_count',    'label': 'Snapshots',         'format': 'number'},
               ])

    _add_table(out, 'Pipeline Summary', '📊',
               _safe_arr(dashboard_data.get('open_pipeline_summary')), [
                   {'key': 'period_key',        'label': 'Period'},
                   {'key': 'stage',             'label': 'Stage'},
                   {'key': 'status',            'label': 'Status'},
                   {'key': 'total_amount',      'label': 'Amount',   'format': 'currency'},
                   {'key': 'weighted_amount',   'label': 'Weighted', 'format': 'currency'},
                   {'key': 'opportunity_count', 'label': 'Count',    'format': 'number'},
               ])

    _add_table(out, 'Booked Revenue', '💰',
               _safe_arr(dashboard_data.get('booked_revenue')), [
                   {'key': 'period_key',    'label': 'Period'},
                   {'key': 'booked_revenue','label': 'Revenue',    'format': 'currency'},
                   {'key': 'discount_total','label': 'Discounts',  'format': 'currency'},
                   {'key': 'line_count',    'label': 'Line Items', 'format': 'number'},
               ])

    _add_table(out, 'Invoiced Revenue', '📃',
               _safe_arr(dashboard_data.get('recent_invoiced_revenue')), [
                   {'key': 'period_key',         'label': 'Period'},
                   {'key': 'invoiced_amount',    'label': 'Invoiced',     'format': 'currency'},
                   {'key': 'outstanding_amount', 'label': 'Outstanding',  'format': 'currency'},
                   {'key': 'paid_amount',        'label': 'Paid',         'format': 'currency'},
               ])

    _add_table(out, 'Cashflow', '💵',
               _safe_arr(dashboard_data.get('recent_cashflow')), [
                   {'key': 'period_key',   'label': 'Period'},
                   {'key': 'paid_amount',  'label': 'Cash Received', 'format': 'currency'},
                   {'key': 'payment_count','label': 'Payments',      'format': 'number'},
               ])

    _add_table(out, 'AR Aging', '🧾',
               _safe_arr(dashboard_data.get('ar_aging')), [
                   {'key': 'aging_bucket',       'label': 'Bucket'},
                   {'key': 'outstanding_amount', 'label': 'Outstanding', 'format': 'currency'},
                   {'key': 'invoice_count',      'label': 'Invoices',    'format': 'number'},
               ])

    # AR Aging by Owner — shows name + role (v3.1)
    _add_table(out, 'AR Aging by Owner', '👤',
               _safe_arr(dashboard_data.get('ar_aging_by_owner')), [
                   {'key': 'owner_name',         'label': 'Owner Name'},
                   {'key': 'owner_role',         'label': 'Role'},
                   {'key': 'outstanding_amount', 'label': 'Outstanding', 'format': 'currency'},
                   {'key': 'invoice_count',      'label': 'Invoices',    'format': 'number'},
               ])

    _add_table(out, 'AR Aging by Account', '🏢',
               _safe_arr(dashboard_data.get('ar_aging_by_account')), [
                   {'key': 'account_id',         'label': 'Account ID',  'format': 'uuid'},
                   {'key': 'outstanding_amount', 'label': 'Outstanding', 'format': 'currency'},
                   {'key': 'invoice_count',      'label': 'Invoices',    'format': 'number'},
               ])

    _add_table(out, 'AR Aging by Product', '📦',
               _safe_arr(dashboard_data.get('ar_aging_by_product')), [
                   {'key': 'product_id',         'label': 'Product ID',  'format': 'uuid'},
                   {'key': 'outstanding_amount', 'label': 'Outstanding', 'format': 'currency'},
                   {'key': 'invoice_count',      'label': 'Invoices',    'format': 'number'},
               ])

    _add_table(out, 'Lead Source Performance', '📣',
               _safe_arr(dashboard_data.get('lead_source_performance')), [
                   {'key': 'lead_source',       'label': 'Source'},
                   {'key': 'pipeline_amount',   'label': 'Pipeline',     'format': 'currency'},
                   {'key': 'weighted_pipeline', 'label': 'Weighted',     'format': 'currency'},
                   {'key': 'opportunity_count', 'label': 'Opportunities','format': 'number'},
               ])

    # Activity Productivity — shows name + role (v3.1)
    _add_table(out, 'Activity Productivity', '📝',
               _safe_arr(dashboard_data.get('activity_productivity')), [
                   {'key': 'owner_name',      'label': 'Owner Name'},
                   {'key': 'owner_role',      'label': 'Role'},
                   {'key': 'activity_type',   'label': 'Type'},
                   {'key': 'activity_count',  'label': 'Total',     'format': 'number'},
                   {'key': 'completed_count', 'label': 'Completed', 'format': 'number'},
                   {'key': 'overdue_count',   'label': 'Overdue',   'format': 'number'},
               ])

    out.append('---')
    out.append('Need more details? Try filtering by owner, account, or product!')

    # ── Meta record counts ────────────────────────────────────────────────────
    meta = {
        'generatedAt': datetime.utcnow().isoformat(),
        'recordCounts': {
            'forecast_summary':      len(_safe_arr(dashboard_data.get('forecast_summary'))),
            'owner_breakdown':       len(_safe_arr(dashboard_data.get('owner_breakdown'))),
            'period_trend':          len(_safe_arr(dashboard_data.get('period_trend'))),
            'ai_vs_human_forecast':  len(_safe_arr(dashboard_data.get('ai_vs_human_forecast'))),
            'forecast_accuracy':     len(_safe_arr(dashboard_data.get('forecast_accuracy'))),
            'pipeline_summary':      len(_safe_arr(dashboard_data.get('open_pipeline_summary'))),
            'booked_revenue':        len(_safe_arr(dashboard_data.get('booked_revenue'))),
            'invoiced_revenue':      len(_safe_arr(dashboard_data.get('recent_invoiced_revenue'))),
            'cashflow':              len(_safe_arr(dashboard_data.get('recent_cashflow'))),
            'ar_aging':              len(_safe_arr(dashboard_data.get('ar_aging'))),
            'lead_source_performance': len(_safe_arr(dashboard_data.get('lead_source_performance'))),
            'activity_productivity': len(_safe_arr(dashboard_data.get('activity_productivity'))),
            'ar_aging_by_owner':     len(_safe_arr(dashboard_data.get('ar_aging_by_owner'))),
            'ar_aging_by_account':   len(_safe_arr(dashboard_data.get('ar_aging_by_account'))),
            'ar_aging_by_product':   len(_safe_arr(dashboard_data.get('ar_aging_by_product'))),
        }
    }

    return {
        'output':         '\n'.join(out),
        'mode':           'dashboard',
        'success':        True,
        'dashboardData':  dashboard_data,
        'summaryMetrics': summary_metrics,
        'params':         echoed_params,
        'meta':           meta,
    }
