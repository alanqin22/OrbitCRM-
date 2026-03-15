"""Response formatter for Leads — Python conversion of n8n Format Response v4.5.

CHANGELOG v4.5
  - convert mode: reads full account/contact/opportunity/address objects from
    sp_leads_v5b; rich conversion confirmation with all entity details.

CHANGELOG v4.4
  - list_employee mode: emits employees[] JSON array (for HTML loadEmployees()
    dropdowns) in addition to markdown output. Returns early — no footer appended.

CHANGELOG v4.2
  - pipeline: works with BOTH old object format {status: count} AND new array
    format [{name, count}] for by_status, by_rating, by_source.

CHANGELOG v4.1
  - ChatResponse includes: leads[], lead, pipeline, employees[], account,
    contact, opportunity, address, accountId, contactId, opportunityId.

Supported modes (13):
  list, get, create, update, qualify, score, convert, archive, restore,
  duplicates, merge, pipeline, list_employee.

Side-channel arrays in return dict:
  leads[]      — full lead array for HTML table rendering (all modes that touch a list)
  lead         — single lead dict (get / create / update / qualify / score / convert)
  pipeline     — pipeline analytics dict
  employees[]  — active employee list for dropdowns (list_employee mode only, early return)
  account      — new account object (convert mode)
  contact      — new contact object (convert mode)
  opportunity  — new opportunity object (convert mode)
  address      — account address object (convert mode)
  accountId    — convenience ID extracted from account (convert mode)
  contactId    — convenience ID extracted from contact (convert mode)
  opportunityId — convenience ID extracted from opportunity (convert mode)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _mode_name(mode: str) -> str:
    return {
        'list':          'Lead List',
        'get':           'Lead Details',
        'create':        'Lead Created',
        'update':        'Lead Updated',
        'qualify':       'Lead Qualified',
        'score':         'Lead Scored',
        'convert':       'Lead Converted',
        'archive':       'Lead Archived',
        'restore':       'Lead Restored',
        'duplicates':    'Duplicate Leads Report',
        'merge':         'Leads Merged',
        'pipeline':      'Lead Pipeline Summary',
        'list_employee': 'Employee List',
    }.get(mode, 'Lead List')


def _status_badge(status: str) -> str:
    return {
        'new':           '[NEW]',
        'working':       '[WORKING]',
        'qualified':     '⭐[QUALIFIED]',
        'converted':     '✔[CONVERTED]',
        'deleted':       '🗑[DELETED]',
        'disqualified':  '[DISQUALIFIED]',
    }.get(str(status or '').lower(), f'[{str(status or "").upper()}]')


def _rating_icon(rating: str) -> str:
    return {'hot': '🔥', 'warm': '☀️', 'cold': '❄️'}.get(str(rating or '').lower(), '')


def _owner_name(l: dict) -> Optional[str]:
    fn = l.get('owner_first_name') or ''
    ln = l.get('owner_last_name') or ''
    name = f"{fn} {ln}".strip()
    return name or None


def _created_by_name(l: dict) -> Optional[str]:
    fn = l.get('created_by_first_name') or ''
    ln = l.get('created_by_last_name') or ''
    name = f"{fn} {ln}".strip()
    return name or None


def _updated_by_name(l: dict) -> Optional[str]:
    fn = l.get('updated_by_first_name') or ''
    ln = l.get('updated_by_last_name') or ''
    name = f"{fn} {ln}".strip()
    return name or None


def _format_address(l: dict) -> Optional[str]:
    parts = [
        l.get('address_line1'), l.get('address_line2'),
        l.get('city'), l.get('province'),
        l.get('postal_code'), l.get('country'),
    ]
    parts = [p for p in parts if p]
    return ', '.join(parts) if parts else None


def _lead_dict(l: dict) -> dict:
    """Build the structured lead dict emitted in the side-channel."""
    return {
        'lead_id':               l.get('lead_id'),
        'first_name':            l.get('first_name'),
        'last_name':             l.get('last_name'),
        'company':               l.get('company'),
        'email':                 l.get('email'),
        'phone':                 l.get('phone'),
        'address_line1':         l.get('address_line1'),
        'address_line2':         l.get('address_line2'),
        'city':                  l.get('city'),
        'province':              l.get('province'),
        'postal_code':           l.get('postal_code'),
        'country':               l.get('country'),
        'status':                l.get('status'),
        'rating':                l.get('rating'),
        'score':                 l.get('score'),
        'source':                l.get('source'),
        'campaign_id':           l.get('campaign_id'),
        'owner_name':            _owner_name(l),
        'created_by_name':       _created_by_name(l),
        'updated_by_name':       _updated_by_name(l),
        'created_at':            l.get('created_at'),
        'updated_at':            l.get('updated_at'),
        'score_updated_at':      l.get('score_updated_at'),
        'qualification_reason':  l.get('qualification_reason'),
        'qualification_date':    l.get('qualification_date'),
        'disqualification_reason': l.get('disqualification_reason'),
        'converted':             l.get('converted'),
        'converted_at':          l.get('converted_at'),
        'converted_account_id':  l.get('converted_account_id'),
        'converted_contact_id':  l.get('converted_contact_id'),
        'converted_opportunity_id': l.get('converted_opportunity_id'),
        'dedupe_group_id':       l.get('dedupe_group_id'),
        'dedupe_confidence':     l.get('dedupe_confidence'),
    }


def _parse_response(db_rows: List[Dict]) -> Dict:
    if not db_rows:
        return {}
    first = db_rows[0]
    for key in ('result', 'sp_leads'):
        val = first.get(key)
        if val is not None:
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    return parsed.get('result', parsed) if isinstance(parsed, dict) else parsed
                except json.JSONDecodeError:
                    pass
            elif isinstance(val, dict):
                return val.get('result', val)
    # If no wrapper key, try treating the row itself as the response
    if 'metadata' in first or 'leads' in first or 'lead' in first:
        return first
    return first


# ============================================================================
# PUBLIC API
# ============================================================================

def format_response(db_rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format sp_leads DB rows into the output dict expected by main.py.

    Returns dict with keys:
      output       — formatted markdown string
      mode         — SP mode string
      report_mode  — internal identifier
      success      — bool
      leads        — list of lead dicts (for HTML table)
      lead         — single lead dict (for detail / mutation modes)
      pipeline     — pipeline analytics dict
      employees    — list (only for list_employee, early return)
      account / contact / opportunity / address — (convert mode only)
      accountId / contactId / opportunityId     — (convert mode only)
    """
    mode     = str(params.get('mode') or 'list').lower().strip()
    response = _parse_response(db_rows)
    metadata = response.get('metadata') or {}

    logger.info(f'Format Response (sp_leads v4.5) — mode={mode}')

    # ── Error check ───────────────────────────────────────────────────────────
    is_error   = metadata.get('status') == 'error' or (
        isinstance(metadata.get('code'), (int, float)) and metadata.get('code', 0) < 0
    )
    is_warning = metadata.get('status') == 'warning' or metadata.get('code') == 100

    if is_error:
        output = (
            f'### ❌ ERROR\n'
            f'**Time:** {_fmt_dt(datetime.utcnow().isoformat())}\n'
            f'**Error Code:** {metadata.get("code")}\n'
            f'**Error Message:** {metadata.get("message", "Unknown error")}\n\n'
            f'Please fix the input and try again.'
        )
        return {'output': output, 'mode': mode, 'report_mode': 'error', 'success': False,
                'leads': [], 'lead': None, 'pipeline': None, 'employees': [],
                'account': None, 'contact': None, 'opportunity': None, 'address': None,
                'accountId': None, 'contactId': None, 'opportunityId': None}

    # ── Mode routing ──────────────────────────────────────────────────────────
    leads:       List[dict] = []
    lead:        Optional[dict] = None
    report_mode  = 'generic'
    report_data: dict = {}

    if mode == 'list':
        report_mode = 'lead_list'
        leads       = response.get('leads') or []
        report_data['pagination'] = {
            'page':         metadata.get('page', 1),
            'pageSize':     metadata.get('page_size', 50),
            'totalRecords': metadata.get('total_records', len(leads)),
            'totalPages':   metadata.get('total_pages', 1),
        }

    elif mode == 'get':
        report_mode = 'lead_detail'
        lead        = response.get('lead')

    elif mode == 'create':
        report_mode = 'lead_created'
        lead        = response.get('lead')
        report_data['possibleDuplicates'] = metadata.get('possible_duplicates') or []

    elif mode == 'update':
        report_mode = 'lead_updated'
        lead        = response.get('lead')

    elif mode == 'qualify':
        report_mode = 'lead_qualified'
        lead        = response.get('lead')

    elif mode == 'score':
        report_mode = 'lead_scored'
        lead        = response.get('lead')

    elif mode == 'convert':
        report_mode = 'lead_converted'
        lead        = response.get('lead')
        acct        = response.get('account')
        cont        = response.get('contact')
        opp         = response.get('opportunity')
        addr        = response.get('address')
        report_data.update({
            'account':     acct,
            'contact':     cont,
            'opportunity': opp,
            'address':     addr,
            'accountId':     (acct.get('account_id')     if acct else None) or response.get('account_id'),
            'contactId':     (cont.get('contact_id')     if cont else None) or response.get('contact_id'),
            'opportunityId': (opp.get('opportunity_id')  if opp  else None) or response.get('opportunity_id'),
        })

    elif mode == 'archive':
        report_mode = 'lead_archived'

    elif mode == 'restore':
        report_mode = 'lead_restored'

    elif mode == 'duplicates':
        report_mode = 'duplicates'
        report_data['duplicates'] = response.get('duplicates') or []

    elif mode == 'merge':
        report_mode = 'lead_merged'
        report_data['keptId']        = response.get('kept_id')
        report_data['archivedCount'] = response.get('archived_count', 0)

    elif mode == 'pipeline':
        report_mode = 'pipeline'
        report_data['pipeline'] = response.get('pipeline') or {}

    elif mode == 'list_employee':
        report_mode = 'list_employee'
        report_data['employees'] = response.get('employees') or []

    else:
        # Auto-detect
        if response.get('leads'):
            report_mode = 'lead_list'
            leads       = response['leads']
            report_data['pagination'] = {
                'page': metadata.get('page', 1), 'pageSize': metadata.get('page_size', 50),
                'totalRecords': metadata.get('total_records', len(leads)), 'totalPages': metadata.get('total_pages', 1),
            }
        elif response.get('lead'):
            report_mode = 'lead_detail'
            lead        = response['lead']
        elif response.get('pipeline'):
            report_mode = 'pipeline'
            report_data['pipeline'] = response['pipeline']

    # =========================================================================
    # OUTPUT BUILDING
    # =========================================================================

    out: List[str] = []
    out.append(f'### 🎯 {_mode_name(mode)}')
    out.append(f'**Time:** {_fmt_dt(datetime.utcnow().isoformat())}')
    out.append('')

    # ── Lead List ─────────────────────────────────────────────────────────────
    if report_mode == 'lead_list':
        if leads:
            pg = report_data.get('pagination', {})
            out.append(
                f'**Page:** {pg.get("page", 1)} of {pg.get("totalPages", 1)} | '
                f'**Total:** {pg.get("totalRecords", len(leads))} leads'
            )
            out.append('')
            for idx, l in enumerate(leads, 1):
                full_name = f"{l.get('first_name') or ''} {l.get('last_name') or ''}".strip() or 'Unknown'
                owner_name    = _owner_name(l)
                created_by    = _created_by_name(l)
                updated_by    = _updated_by_name(l)
                rating_icon   = _rating_icon(l.get('rating') or '')

                # Embed lead_id for web page
                out.append(f"<!--LEAD_DATA:{l.get('lead_id')}-->")

                # Line 1: Name | Company | Email | Phone
                out.append(
                    f"**{idx}. {full_name}** | {l.get('company') or 'N/A'} | "
                    f"{l.get('email') or 'N/A'} | {l.get('phone') or 'N/A'}"
                )

                # Line 2: Status | Rating | Score | Source | Owner
                line2 = (
                    f"{_status_badge(l.get('status') or '')} | "
                    f"{rating_icon} {l.get('rating') or 'N/A'} | "
                    f"Score: {l.get('score') if l.get('score') is not None else 'N/A'} | "
                    f"Source: {l.get('source') or 'N/A'}"
                )
                if owner_name:
                    line2 += f" | Owner: {owner_name}"
                out.append(line2)

                # Address
                addr = _format_address(l)
                if addr:
                    out.append(f'📍 {addr}')

                # Audit line
                parts = []
                if created_by: parts.append(f'Created by: {created_by}')
                if updated_by: parts.append(f'Updated by: {updated_by}')
                if l.get('qualification_reason'): parts.append(f"Qual: {l['qualification_reason']}")
                if parts:
                    out.append(' | '.join(parts))

                out.append(f"Created: {_fmt_dt(l.get('created_at'))} | Updated: {_fmt_dt(l.get('updated_at'))}")
                out.append('')
        else:
            out.append('No leads found.')

    # ── Lead Detail ───────────────────────────────────────────────────────────
    elif report_mode == 'lead_detail' and lead:
        full_name   = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
        owner_name  = _owner_name(lead)
        created_by  = _created_by_name(lead)
        updated_by  = _updated_by_name(lead)
        rating_icon = _rating_icon(lead.get('rating') or '')

        out.append(f"<!--LEAD_ID:{lead.get('lead_id')}-->")
        out.append('| Field | Value |')
        out.append('|-------|-------|')
        out.append(f"| **Lead ID** | {lead.get('lead_id')} |")
        if full_name: out.append(f'| **Name** | {full_name} |')
        if lead.get('company'):  out.append(f"| **Company** | {lead['company']} |")
        if lead.get('email'):    out.append(f"| **Email** | {lead['email']} |")
        if lead.get('phone'):    out.append(f"| **Phone** | {lead['phone']} |")

        # Address block
        if lead.get('address_line1'):
            addr2 = f", {lead['address_line2']}" if lead.get('address_line2') else ''
            out.append(f"| **Address** | {lead['address_line1']}{addr2} |")
        city_parts = [lead.get('city'), lead.get('province'), lead.get('postal_code')]
        city_line  = ', '.join(p for p in city_parts if p)
        if city_line: out.append(f'| **City / Province / Postal** | {city_line} |')
        if lead.get('country'): out.append(f"| **Country** | {lead['country']} |")

        out.append(f"| **Status** | {_status_badge(lead.get('status') or '')} |")
        if lead.get('rating'):
            out.append(f"| **Rating** | {rating_icon} {lead['rating']} |")
        if lead.get('score') is not None:
            out.append(f"| **Score** | {lead['score']} |")
        if lead.get('source'):      out.append(f"| **Source** | {lead['source']} |")
        if owner_name:              out.append(f'| **Owner** | {owner_name} |')
        if created_by:              out.append(f'| **Created By** | {created_by} |')
        if updated_by:              out.append(f'| **Updated By** | {updated_by} |')
        out.append(f"| **Created** | {_fmt_dt(lead.get('created_at'))} |")
        out.append(f"| **Updated** | {_fmt_dt(lead.get('updated_at'))} |")

        # Qualification info
        if lead.get('qualification_reason'):
            out.append('')
            out.append('**Qualification Info:**')
            out.append(f"| Qualification Reason | {lead['qualification_reason']} |")
            if lead.get('qualification_date'):
                out.append(f"| Qualification Date | {_fmt_dt(lead['qualification_date'])} |")

        # Conversion info
        if lead.get('converted'):
            out.append('')
            out.append('**Conversion Info:**')
            out.append('| Converted | Yes |')
            if lead.get('converted_at'):
                out.append(f"| Converted At | {_fmt_dt(lead['converted_at'])} |")
            if lead.get('converted_account_id'):
                out.append(f"| Account ID | {lead['converted_account_id']} |")
            if lead.get('converted_contact_id'):
                out.append(f"| Contact ID | {lead['converted_contact_id']} |")
            if lead.get('converted_opportunity_id'):
                out.append(f"| Opportunity ID | {lead['converted_opportunity_id']} |")

        # Dedupe info
        if lead.get('dedupe_group_id'):
            out.append('')
            out.append('**Deduplication Info:**')
            out.append(f"| Dedupe Group | {lead['dedupe_group_id']} |")
            if lead.get('dedupe_confidence') is not None:
                out.append(f"| Confidence | {round(lead['dedupe_confidence'] * 100)}% |")

    # ── Lead Qualified ────────────────────────────────────────────────────────
    elif report_mode == 'lead_qualified' and lead:
        full_name  = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
        updated_by = _updated_by_name(lead)

        out.append('⭐ **Lead Qualified Successfully!**')
        out.append('')
        out.append(f"<!--LEAD_ID:{lead.get('lead_id')}-->")
        out.append('| Field | Value |')
        out.append('|-------|-------|')
        out.append(f"| **Lead ID** | {lead.get('lead_id')} |")
        if full_name:                    out.append(f'| **Name** | {full_name} |')
        out.append('| **Status** | ⭐ QUALIFIED |')
        if lead.get('qualification_reason'):
            out.append(f"| **Qualification Reason** | {lead['qualification_reason']} |")
        if lead.get('qualification_date'):
            out.append(f"| **Qualification Date** | {_fmt_dt(lead['qualification_date'])} |")
        if updated_by:                   out.append(f'| **Updated By** | {updated_by} |')
        if lead.get('company'):          out.append(f"| **Company** | {lead['company']} |")
        if lead.get('email'):            out.append(f"| **Email** | {lead['email']} |")

    # ── Lead Created ──────────────────────────────────────────────────────────
    elif report_mode == 'lead_created':
        dups = report_data.get('possibleDuplicates') or []
        if is_warning and dups:
            out.append('⚠️ **Lead Created with Warning!**')
            out.append('')
            out.append(f'**Warning:** {len(dups)} existing lead(s) found with same email.')
            out.append('')
            out.append('**Possible Duplicates:**')
            for idx, dup in enumerate(dups, 1):
                out.append(f"   {idx}. {dup.get('name') or 'N/A'} — {dup.get('company') or 'N/A'} ({dup.get('status')})")
            out.append('')
            out.append('*Consider merging or updating instead of creating duplicate.*')
        else:
            out.append('✅ **Lead Created Successfully!**')
            out.append('')
            if lead:
                out.append(f"<!--LEAD_ID:{lead.get('lead_id')}-->")
                full_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
                out.append('| Field | Value |')
                out.append('|-------|-------|')
                out.append(f"| **Lead ID** | {lead.get('lead_id')} |")
                if full_name:              out.append(f'| **Name** | {full_name} |')
                if lead.get('company'):    out.append(f"| **Company** | {lead['company']} |")
                if lead.get('email'):      out.append(f"| **Email** | {lead['email']} |")
                if lead.get('phone'):      out.append(f"| **Phone** | {lead['phone']} |")
                if lead.get('address_line1'):
                    addr2 = f", {lead['address_line2']}" if lead.get('address_line2') else ''
                    out.append(f"| **Address** | {lead['address_line1']}{addr2} |")
                city_parts = [lead.get('city'), lead.get('province'), lead.get('postal_code')]
                city_line  = ', '.join(p for p in city_parts if p)
                if city_line: out.append(f'| **City / Province / Postal** | {city_line} |')
                if lead.get('country'): out.append(f"| **Country** | {lead['country']} |")
                out.append(f"| **Status** | {lead.get('status') or 'new'} |")

    # ── Lead Updated ──────────────────────────────────────────────────────────
    elif report_mode == 'lead_updated' and lead:
        full_name  = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
        updated_by = _updated_by_name(lead)
        rating_icon = _rating_icon(lead.get('rating') or '')

        out.append('✅ **Lead Updated Successfully!**')
        out.append('')
        out.append(f"<!--LEAD_ID:{lead.get('lead_id')}-->")
        out.append('| Field | Value |')
        out.append('|-------|-------|')
        out.append(f"| **Lead ID** | {lead.get('lead_id')} |")
        if full_name:              out.append(f'| **Name** | {full_name} |')
        if lead.get('company'):    out.append(f"| **Company** | {lead['company']} |")
        if lead.get('email'):      out.append(f"| **Email** | {lead['email']} |")
        if lead.get('phone'):      out.append(f"| **Phone** | {lead['phone']} |")
        if lead.get('address_line1'):
            addr2 = f", {lead['address_line2']}" if lead.get('address_line2') else ''
            out.append(f"| **Address** | {lead['address_line1']}{addr2} |")
        city_parts = [lead.get('city'), lead.get('province'), lead.get('postal_code')]
        city_line  = ', '.join(p for p in city_parts if p)
        if city_line: out.append(f'| **City / Province / Postal** | {city_line} |')
        if lead.get('country'):    out.append(f"| **Country** | {lead['country']} |")
        out.append(f"| **Status** | {lead.get('status') or 'N/A'} |")
        if lead.get('rating'):
            out.append(f"| **Rating** | {rating_icon} {lead['rating']} |")
        if lead.get('score') is not None:
            out.append(f"| **Score** | {lead['score']} |")
        out.append(f"| **Updated** | {_fmt_dt(lead.get('updated_at'))} |")
        if updated_by: out.append(f'| **Updated By** | {updated_by} |')

    # ── Lead Scored ───────────────────────────────────────────────────────────
    elif report_mode == 'lead_scored' and lead:
        full_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
        out.append('📊 **Lead Score Updated!**')
        out.append('')
        out.append(f"<!--LEAD_ID:{lead.get('lead_id')}-->")
        out.append('| Field | Value |')
        out.append('|-------|-------|')
        out.append(f"| **Lead ID** | {lead.get('lead_id')} |")
        if full_name: out.append(f'| **Name** | {full_name} |')
        out.append(f"| **New Score** | **{lead.get('score')}** |")
        if lead.get('score_updated_at'):
            out.append(f"| **Score Updated** | {_fmt_dt(lead['score_updated_at'])} |")

    # ── Lead Converted ────────────────────────────────────────────────────────
    elif report_mode == 'lead_converted':
        out.append('🎉 **Lead Converted Successfully!**')
        out.append('')
        out.append('The lead has been converted — a new Account, Contact, and Opportunity have been created.')
        out.append('')

        # Converted lead summary
        if lead:
            full_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
            out.append('**🧑 Converted Lead**')
            out.append('| Field | Value |')
            out.append('|-------|-------|')
            if full_name:               out.append(f'| Name | {full_name} |')
            if lead.get('company'):     out.append(f"| Company | {lead['company']} |")
            if lead.get('email'):       out.append(f"| Email | {lead['email']} |")
            if lead.get('phone'):       out.append(f"| Phone | {lead['phone']} |")
            out.append('| Status | ✔ CONVERTED |')
            if lead.get('converted_at'):
                out.append(f"| Converted At | {_fmt_dt(lead['converted_at'])} |")
            if lead.get('qualification_reason'):
                out.append(f"| Qualification | {lead['qualification_reason']} |")
            out.append('')

        # New Account
        acct = report_data.get('account')
        if acct:
            out.append('**🏢 New Account Created**')
            out.append('| Field | Value |')
            out.append('|-------|-------|')
            if acct.get('account_name'): out.append(f"| Account Name | {acct['account_name']} |")
            if acct.get('account_id'):   out.append(f"| Account ID | `{acct['account_id']}` |")
            if acct.get('status'):       out.append(f"| Status | {acct['status']} |")
            if acct.get('industry'):     out.append(f"| Industry | {acct['industry']} |")
            if acct.get('phone'):        out.append(f"| Phone | {acct['phone']} |")
            if acct.get('email'):        out.append(f"| Email | {acct['email']} |")
            if acct.get('website'):      out.append(f"| Website | {acct['website']} |")
            if acct.get('created_at'):   out.append(f"| Created At | {_fmt_dt(acct['created_at'])} |")
            out.append('')

        # Account Address
        addr = report_data.get('address') or {}
        if addr.get('line1') or addr.get('city') or addr.get('province'):
            out.append('**📍 Account Address**')
            out.append('| Field | Value |')
            out.append('|-------|-------|')
            if addr.get('line1'):
                street = f"{addr['line1']}{', ' + addr['line2'] if addr.get('line2') else ''}"
                out.append(f'| Street | {street} |')
            if addr.get('city'):        out.append(f"| City | {addr['city']} |")
            if addr.get('province'):    out.append(f"| Province | {addr['province']} |")
            if addr.get('postal_code'): out.append(f"| Postal Code | {addr['postal_code']} |")
            if addr.get('country'):     out.append(f"| Country | {addr['country']} |")
            out.append('')

        # New Contact
        cont = report_data.get('contact')
        if cont:
            c_name = f"{cont.get('first_name') or ''} {cont.get('last_name') or ''}".strip()
            out.append('**👤 New Contact Created**')
            out.append('| Field | Value |')
            out.append('|-------|-------|')
            if c_name:                     out.append(f'| Name | {c_name} |')
            if cont.get('contact_id'):     out.append(f"| Contact ID | `{cont['contact_id']}` |")
            if cont.get('email'):          out.append(f"| Email | {cont['email']} |")
            if cont.get('phone'):          out.append(f"| Phone | {cont['phone']} |")
            if cont.get('role'):           out.append(f"| Role | {cont['role']} |")
            if cont.get('status'):         out.append(f"| Status | {cont['status']} |")
            if cont.get('created_at'):     out.append(f"| Created At | {_fmt_dt(cont['created_at'])} |")
            out.append('')

        # New Opportunity
        opp = report_data.get('opportunity')
        if opp:
            out.append('**💼 New Opportunity Created**')
            out.append('| Field | Value |')
            out.append('|-------|-------|')
            if opp.get('name'):              out.append(f"| Opportunity | {opp['name']} |")
            if opp.get('opportunity_id'):    out.append(f"| Opportunity ID | `{opp['opportunity_id']}` |")
            if opp.get('stage'):             out.append(f"| Stage | {opp['stage']} |")
            if opp.get('status'):            out.append(f"| Status | {opp['status']} |")
            if opp.get('lead_source'):       out.append(f"| Lead Source | {opp['lead_source']} |")
            if opp.get('amount') is not None: out.append(f"| Amount | {opp['amount']} |")
            if opp.get('probability') is not None: out.append(f"| Probability | {opp['probability']}% |")
            if opp.get('close_date'):        out.append(f"| Close Date | {_fmt_dt(opp['close_date'])} |")
            if opp.get('description'):       out.append(f"| Description | {opp['description']} |")
            if opp.get('created_at'):        out.append(f"| Created At | {_fmt_dt(opp['created_at'])} |")
            out.append('')

    # ── Archive / Restore ─────────────────────────────────────────────────────
    elif report_mode in ('lead_archived', 'lead_restored'):
        action = 'Archived' if report_mode == 'lead_archived' else 'Restored'
        icon   = '🗑' if report_mode == 'lead_archived' else '♻️'
        out.append(f'{icon} **Lead {action} Successfully!**')
        out.append('')
        if metadata.get('message'):
            out.append(f"**Message:** {metadata['message']}")

    # ── Duplicates ────────────────────────────────────────────────────────────
    elif report_mode == 'duplicates':
        out.append('**Duplicate Leads Analysis**')
        out.append('')
        dups = report_data.get('duplicates') or []
        if dups:
            out.append(f'Found **{len(dups)}** potential duplicate groups.')
            out.append('')
            for idx, group in enumerate(dups, 1):
                out.append(f"**Group {idx}:** {group.get('email') or 'Unknown email'}")
                for lidx, l in enumerate((group.get('leads') or []), 1):
                    fn   = f"{l.get('first_name') or ''} {l.get('last_name') or ''}".strip() or 'Unknown'
                    out.append(f"   {lidx}. {fn} ({l.get('status')}) — ID: {l.get('lead_id')}")
                out.append('')
        else:
            out.append('✅ **No duplicate leads found!**')

    # ── Merge ─────────────────────────────────────────────────────────────────
    elif report_mode == 'lead_merged':
        out.append('🔀 **Leads Merged Successfully!**')
        out.append('')
        out.append('| Result | Value |')
        out.append('|--------|-------|')
        if report_data.get('keptId'):
            out.append(f"| **Winner Lead ID** | {report_data['keptId']} |")
        if report_data.get('archivedCount') is not None:
            out.append(f"| **Leads Archived** | {report_data['archivedCount']} |")

    # ── Pipeline ──────────────────────────────────────────────────────────────
    elif report_mode == 'pipeline':
        pipeline = report_data.get('pipeline') or {}
        out.append('**Lead Pipeline Analysis**')
        out.append('')

        if pipeline.get('conversion_rate') is not None:
            out.append(f"**Conversion Rate:** {pipeline['conversion_rate']}%")
        if pipeline.get('avg_score') is not None:
            out.append(f"**Average Score:** {pipeline['avg_score']}")
        out.append('')

        def _render_group(title: str, data, icon_fn=None):
            if not data:
                return
            # Support BOTH old object format {status: count} AND array [{name, count}]
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = [{'name': k, 'count': v} for k, v in data.items()]
            else:
                return
            if not items:
                return
            header_name = 'Rating' if title == 'By Rating' else title.replace('By ', '')
            out.append(f'**{title}**')
            out.append(f'| {header_name} | Count |')
            out.append('|--------|------:|')
            for item in items:
                label = item.get('name') or 'unknown'
                count = item.get('count', 0)
                icon  = icon_fn(label) if icon_fn else ''
                prefix = f'{icon} ' if icon else ''
                out.append(f'| {prefix}{label} | **{count}** |')
            out.append('')

        _render_group('By Status', pipeline.get('by_status'))
        _render_group('By Rating', pipeline.get('by_rating'), _rating_icon)
        _render_group('By Source', pipeline.get('by_source'))

        if pipeline.get('dedupe_stats'):
            ds = pipeline['dedupe_stats']
            out.append('**Deduplication Stats**')
            if ds.get('dedupe_groups') is not None:
                out.append(f"- Dedupe Groups: {ds['dedupe_groups']}")
            if ds.get('merged_leads') is not None:
                out.append(f"- Merged Leads: {ds['merged_leads']}")
            out.append('')

    # ── list_employee — EARLY RETURN (no footer) ──────────────────────────────
    elif report_mode == 'list_employee':
        employees = report_data.get('employees') or []
        if employees:
            out.append(f'**{len(employees)} active employee(s) loaded.**')
            out.append('')
            out.append('| Name | Employee UUID |')
            out.append('|------|--------------|')
            for e in employees:
                name = f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip()
                out.append(f"| {name} | `{e.get('employee_uuid') or 'N/A'}` |")
        else:
            out.append('No active employees found.')

        return {
            'output':      '\n'.join(out),
            'mode':        mode,
            'report_mode': report_mode,
            'success':     True,
            'leads':       [],
            'lead':        None,
            'pipeline':    None,
            'employees':   employees,
            'account':     None, 'contact': None, 'opportunity': None, 'address': None,
            'accountId':   None, 'contactId': None, 'opportunityId': None,
        }

    # ── Generic fallback ──────────────────────────────────────────────────────
    else:
        out.append('**Action completed successfully**')
        if metadata.get('message'):
            out.append(f"Message: {metadata['message']}")

    # ── Footer ────────────────────────────────────────────────────────────────
    out.append('')
    out.append('---')
    out.append('Need anything else? Just ask!')

    # ── Build structured side-channel lead data ───────────────────────────────
    leads_out = [_lead_dict(l) for l in leads]
    lead_out  = _lead_dict(lead) if lead else (
        _lead_dict(report_data['lead']) if report_data.get('lead') else None
    )

    return {
        'output':        '\n'.join(out),
        'mode':          mode,
        'report_mode':   report_mode,
        'success':       True,
        'leads':         leads_out,
        'lead':          lead_out,
        'pipeline':      report_data.get('pipeline'),
        'employees':     [],
        'account':       report_data.get('account'),
        'contact':       report_data.get('contact'),
        'opportunity':   report_data.get('opportunity'),
        'address':       report_data.get('address'),
        'accountId':     report_data.get('accountId'),
        'contactId':     report_data.get('contactId'),
        'opportunityId': report_data.get('opportunityId'),
    }
