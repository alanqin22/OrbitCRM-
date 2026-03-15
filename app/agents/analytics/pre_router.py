"""Analytics Pre-Router v2.0 — Python conversion of n8n 'pre router' node.

OVERVIEW
  Inspects every incoming request and either ROUTES it directly to the SQL
  builder (router_action=True) OR passes it through to the AI Agent
  (router_action=False).

  ARCHITECTURAL PRINCIPLE:
    Structured report triggers  → ROUTED directly (no AI Agent)
    Ambiguous / NL queries      → AI Agent fallback

  Unlike every other CRM agent, the Analytics pre-router has only ONE trigger
  prefix: "analytics report:". ALL structured calls from the HTML dashboard
  use this single prefix, distinguished by the chatInput.reportType field.

DIRECT-ROUTE TRIGGERS
  All messages prefixed with "analytics report:" are routed directly.

  ┌────────────────────────────┬────────────────────────────────────────────┐
  │ chatInput.reportType       │ SP p_report_type                           │
  ├────────────────────────────┼────────────────────────────────────────────┤
  │ "full_dashboard"           │ NULL (all sections — reportType omitted)   │
  │ "forecast_summary"         │ "forecast_summary"                         │
  │ "pipeline_summary"         │ "pipeline_summary"                         │
  │ "revenue_summary"          │ "revenue_summary"                          │
  │ "ar_aging"                 │ "ar_aging"                                 │
  │ "cashflow"                 │ "cashflow"                                 │
  │ "invoiced_revenue"         │ "invoiced_revenue"                         │
  │ "lead_source"              │ "lead_source"                              │
  │ "owner_breakdown"          │ "owner_breakdown"                          │
  │ "activity_productivity"    │ "activity_productivity"                    │
  │ "ai_vs_human"              │ "ai_vs_human"                              │
  └────────────────────────────┴────────────────────────────────────────────┘

  chatInput fields used:
    reportType  : TEXT           (see table above)
    startDate   : YYYY-MM-DD     (null → AR Aging snapshot mode)
    endDate     : YYYY-MM-DD     (null → AR Aging snapshot mode)
    ownerId     : UUID (optional)
    accountId   : UUID (optional)
    productId   : UUID (optional)

AR AGING SPECIAL CASE:
  When reportType='ar_aging' and no dates are provided, the SP enters snapshot
  mode (returns current-state AR aging, recent cashflow, open pipeline).
  In this case startDate and endDate are intentionally omitted from params.

FULL DASHBOARD:
  When reportType='full_dashboard' (or not set), reportType is omitted from
  params so the SP defaults to returning all sections (p_report_type = NULL).

PASSTHRU (AI Agent fallback):
  Any message that does NOT start with "analytics report:" is forwarded to the
  AI Agent as a natural-language query.
  Examples:
    "Show pipeline for Q1 2025"
    "What's our year-to-date revenue?"
    "Compare AI forecast vs actuals for last quarter"

CHANGELOG
  v2.0 — Complete rewrite. Direct-route architecture for all 11 report types.
          AR Aging snapshot mode (no dates). NL fallback preserved.
  v1.0 — Original release (passthru / NL normalisation only).
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)

VALID_REPORT_TYPES = {
    'full_dashboard',
    'forecast_summary',
    'pipeline_summary',
    'revenue_summary',
    'ar_aging',
    'cashflow',
    'invoiced_revenue',
    'lead_source',
    'owner_breakdown',
    'activity_productivity',
    'ai_vs_human',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _val(v: Any) -> Optional[Any]:
    """Coerce empty string / None → None; otherwise return as-is."""
    if v is None or v == '':
        return None
    return v


def _extract_uuid(s: Any) -> Optional[str]:
    m = UUID_RE.search(str(s or ''))
    return m.group(0) if m else None


def _routed(params: dict) -> dict:
    logger.info(
        f"→ ROUTED: reportType={params.get('reportType', 'full_dashboard')} "
        f"| startDate={params.get('startDate')} | endDate={params.get('endDate')}"
    )
    return {'router_action': True, 'params': params}


def _passthru(raw: str) -> dict:
    logger.info(f"→ PASSTHRU: AI Agent | message={raw[:80]!r}")
    return {'router_action': False, 'current_message': raw.strip()}


# ============================================================================
# MAIN ROUTER
# ============================================================================

def route_request(body: dict, chat_input: dict, session_id: str) -> dict:
    """
    Inspect the incoming request and return a routing decision.

    Routed:   { 'router_action': True,  'params': { ... } }
    Passthru: { 'router_action': False, 'current_message': str }
    """
    logger.info('=== Analytics Pre-Router v2.0 ===')
    logger.info(f'SessionId: {session_id}')

    raw = (chat_input.get('message') or body.get('message') or '').strip()
    msg = raw.lower()
    logger.info(f'Message: {raw[:120]}')

    # ── "analytics report:" ──────────────────────────────────────────────────
    if msg.startswith('analytics report:'):
        report_type = _val(chat_input.get('reportType')) or 'full_dashboard'
        start_date  = _val(chat_input.get('startDate'))
        end_date    = _val(chat_input.get('endDate'))
        owner_id    = _val(chat_input.get('ownerId'))    or _extract_uuid(chat_input.get('ownerId', ''))
        account_id  = _val(chat_input.get('accountId')) or _extract_uuid(chat_input.get('accountId', ''))
        product_id  = _val(chat_input.get('productId')) or _extract_uuid(chat_input.get('productId', ''))

        logger.info(
            f'[analytics report] type={report_type} '
            f'| from={start_date} | to={end_date}'
        )

        # AR Aging special case: no dates → SP snapshot mode (NULL date mode)
        if report_type == 'ar_aging' and not start_date and not end_date:
            logger.info('[ar_aging] No date range → SP snapshot mode (NULL dates)')
            return _routed({'reportType': 'ar_aging'})

        # Build params — for full_dashboard, omit reportType so SP returns all sections
        params: dict = {}
        if start_date:  params['startDate']  = start_date
        if end_date:    params['endDate']     = end_date
        if owner_id:    params['ownerId']     = owner_id
        if account_id:  params['accountId']   = account_id
        if product_id:  params['productId']   = product_id
        if report_type != 'full_dashboard':
            params['reportType'] = report_type

        return _routed(params)

    # ── Fallback: AI Agent ───────────────────────────────────────────────────
    return _passthru(raw)
