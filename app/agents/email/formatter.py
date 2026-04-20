"""Response formatter for EmailAgent."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fmt_dt(value) -> str:
    if not value:
        return 'N/A'
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt.strftime('%b %d, %Y %I:%M %p')
    except (ValueError, AttributeError):
        return str(value) or 'N/A'


def _extract_rows(db_rows: List) -> List[dict]:
    """Unwrap rows from execute_sp or raw query."""
    out = []
    for row in db_rows:
        if isinstance(row, dict):
            result = row.get('result', row)
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except Exception:
                    pass
            out.append(result)
    return out


def format_response(db_rows: List, params: dict, extra: dict = None) -> Dict[str, Any]:
    """
    Format the EmailAgent response.
    extra dict may contain: emails=[], events=[], sent_result={}, status_text=''
    """
    extra    = extra or {}
    mode     = str(params.get('mode') or 'unknown')
    emails   = extra.get('emails', [])
    events   = extra.get('events', [])
    status   = extra.get('status_text', '')
    sent_res = extra.get('sent_result', {})

    # ── imap_inbox ─────────────────────────────────────────────────────────────
    if mode == 'imap_inbox':
        count = len(emails)
        if count == 0:
            output = 'Inbox is empty — no emails found.'
        else:
            lines = [f'**Inbox** — {count} email(s)\n']
            for i, em in enumerate(emails, 1):
                lines.append(
                    f'{i}. **{em.get("subject","(no subject)")}**\n'
                    f'   From: {em.get("from","")}\n'
                    f'   Date: {em.get("date","")}\n'
                    f'   {em.get("preview","")[:120]}'
                )
            output = '\n'.join(lines)
        return {'output': output, 'mode': mode, 'emails': emails, 'success': True}

    # ── imap_search ────────────────────────────────────────────────────────────
    if mode == 'imap_search':
        query = params.get('query', '')
        count = len(emails)
        if count == 0:
            output = f'No emails found matching "{query}".'
        else:
            lines = [f'**Search results for "{query}"** — {count} email(s)\n']
            for i, em in enumerate(emails, 1):
                lines.append(
                    f'{i}. **{em.get("subject","(no subject)")}**\n'
                    f'   From: {em.get("from","")}\n'
                    f'   Date: {em.get("date","")}\n'
                )
            output = '\n'.join(lines)
        return {'output': output, 'mode': mode, 'emails': emails, 'success': True}

    # ── sent_emails ────────────────────────────────────────────────────────────
    if mode == 'sent_emails':
        rows = _extract_rows(db_rows)
        if not rows:
            output = 'No sent emails found in audit log.'
        else:
            lines = [f'**Sent Emails** — {len(rows)} record(s)\n']
            for i, r in enumerate(rows, 1):
                lines.append(
                    f'{i}. To: {r.get("to","?")}  |  '
                    f'Subject: {r.get("subject","?")}  |  '
                    f'Date: {_fmt_dt(r.get("date",""))}'
                )
            output = '\n'.join(lines)
        return {'output': output, 'mode': mode, 'emails': rows, 'success': True}

    # ── event_inbox ────────────────────────────────────────────────────────────
    if mode == 'event_inbox':
        rows = _extract_rows(db_rows)
        raw_events = events or rows
        if not raw_events:
            output = 'No pending events in EmailAgent inbox.'
        else:
            lines = [f'**Agent Event Inbox** — {len(raw_events)} event(s)\n']
            for ev in raw_events:
                if isinstance(ev, dict):
                    lines.append(
                        f'• {ev.get("event_type","?")} | {ev.get("summary","")[:100]}'
                    )
            output = '\n'.join(lines)
        return {'output': output, 'mode': 'heartbeat', 'events': raw_events, 'success': True}

    # ── list_templates ─────────────────────────────────────────────────────────
    if mode == 'list_templates':
        rows = _extract_rows(db_rows)
        if not rows:
            output = 'No email templates found.'
        else:
            lines = [f'**Email Templates** — {len(rows)} template(s)\n']
            for r in rows:
                status_icon = '✓' if r.get('is_active') else '✗'
                lines.append(
                    f'{status_icon} **{r.get("event_type","?")}**  |  '
                    f'{r.get("subject_tpl","")[:60]}'
                )
            output = '\n'.join(lines)
        return {'output': output, 'mode': mode, 'templates': rows, 'success': True}

    # ── send_template / send_email ──────────────────────────────────────────────
    if mode in ('send_template', 'send_email'):
        if sent_res.get('success'):
            output = (
                f'Email sent successfully.\n'
                f'To: {sent_res.get("to","?")}\n'
                f'Subject: {sent_res.get("subject","?")}'
            )
        else:
            output = f'Failed to send email: {sent_res.get("message","Unknown error")}'
        return {
            'output':   output,
            'mode':     'sent_email',
            'success':  sent_res.get('success', False),
            'to':       sent_res.get('to'),
            'subject':  sent_res.get('subject'),
        }

    # ── agent_status ───────────────────────────────────────────────────────────
    if mode == 'agent_status':
        if status:
            output = status
        else:
            rows = _extract_rows(db_rows)
            r = rows[0] if rows else {}
            output = (
                f'**EmailAgent Status: Online**\n'
                f'Subscriptions active: {r.get("active_subscriptions", "?")}\n'
                f'Emails sent (24h): {r.get("sent_24h", "?")}\n'
                f'Unresolved memory messages: {r.get("unresolved_memory", "?")}\n'
                f'SMTP: {r.get("smtp", "mail.agentorc.ca:465")}\n'
                f'IMAP: {r.get("imap", "mail.agentorc.ca:993")}'
            )
        return {'output': output, 'mode': mode, 'success': True}

    # ── conversational fallback ─────────────────────────────────────────────────
    rows = _extract_rows(db_rows)
    output = str(rows[0]) if rows else 'Done.'
    return {'output': output, 'mode': mode, 'success': True}
