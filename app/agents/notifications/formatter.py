"""Response formatter for Notifications — Python conversion of n8n Format Response v2.6.

CHANGELOG v2.6
  - list mode: Added "Read / Unread" column with [TOGGLE:uuid:status:emp_uuid] markers.
  - list mode: [ACTIONBAR] marker replaces footer action links.
  - Added mark_unread and mark_all_unread mode support.

CHANGELOG v2.5
  - inspect_notification: [BACKTOLIST] marker at top; full JSON dump via ```json block.
  - inspect_notification: body cleanup removes "from ? to ?" placeholder artifacts.
  - inspect_notification: triggered-by employee name lookup from hardcoded map.

Supported modes (9):
  list, unread_count, poll, click, mark_read, mark_unread,
  mark_all_read, mark_all_unread, inspect_notification.

Frontend markers injected into output:
  [TOGGLE:uuid:status:emp_uuid]  — Read/Unread toggle button in list table
  [ACTIONBAR]                    — Action bar widget below list table
  [INSPECT:uuid]                 — Inspect button in list table
  [BACKTOLIST]                   — Back to list button at top of inspector
  [ACTION:text]                  — Clickable action link (non-list modes)

Result key from SP:  'sp_notifications'  (NOT 'result' — unique to this module)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENT_ICONS: Dict[str, str] = {
    'lead.created':             '🧲',
    'lead.assigned':            '👤',
    'lead.converted':           '🔄',
    'opportunity.created':      '💼',
    'opportunity.stage_changed':'📈',
    'opportunity.won':          '🏆',
    'opportunity.lost':         '❌',
    'invoice.created':          '🧾',
    'invoice.overdue':          '⚠️',
    'invoice.paid':             '💰',
    'payment.received':         '💵',
    'payment.failed':           '⛔',
    'activity.completed':       '📋',
    'activity.due':             '⏰',
    'contract.sent':            '📤',
    'contract.viewed':          '👀',
    'contract.signed':          '✍️',
    'contract.rejected':        '🚫',
    'contract.expired':         '⌛',
}

# Hardcoded employee name lookup — matches n8n formatter EMPLOYEE_NAMES map
EMPLOYEE_NAMES: Dict[str, str] = {
    'a1451ad6-310c-4bcc-ba17-dd383a881ee8': 'Julia Martin',
    'bc80fb0e-57b9-461a-9490-8aa68bad1901': 'Daniel Lee',
    'ca8eb9a8-f27a-428d-9657-59c9b8a2db16': 'Karen Patel',
    '76dd79c3-ebd9-4abf-b6e7-9a551365a7d3': 'Robert Garcia',
    '02cb6f2d-8e0f-4f50-a710-dbaa24285ed6': 'Sophia Nguyen',
    '367109f6-5145-495c-b11b-fe090c1f6f39': 'Lisa Jones',
    '307cc6ac-eac7-46a2-87ed-bf20e9785862': 'Sarah Johnson',
    '67f0a5b1-0a31-4f8c-b9e8-df8b583871bf': 'Mike Chen',
    '25eaf35e-3f65-4a95-89fe-bcfd06e0c69d': 'System Admin',
}

STANDARD_FOOTER = [
    '',
    '---',
    '[ACTION:Show notifications]',
    '[ACTION:Open Notification Center]',
]


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


def _event_icon(event_type: str) -> str:
    return EVENT_ICONS.get(str(event_type or ''), '•')


def _employee_name(uuid: Optional[str]) -> Optional[str]:
    if not uuid:
        return None
    return EMPLOYEE_NAMES.get(str(uuid))


def _mode_name(mode: str) -> str:
    return {
        'list':                 'Notification List',
        'unread_count':         'Unread Count',
        'poll':                 'Real-Time Polling',
        'click':                'Notification Opened',
        'mark_read':            'Notification Marked Read',
        'mark_unread':          'Notification Marked Unread',
        'mark_all_read':        'All Notifications Marked Read',
        'mark_all_unread':      'All Notifications Marked Unread',
        'inspect_notification': 'Notification Inspector',
    }.get(mode, 'Unknown')


def _clean_body(body: str, event_type: str) -> str:
    """
    Remove unresolved '?' template placeholders from inspect body text.
    Mirrors the JS regex cleanup in the n8n formatter.
    """
    text = body or ''
    # Remove "from ? to ?" and "moved from ? to ?" patterns
    text = re.sub(r'\s*from \?\s*to \?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*moved\s*$', '', text, flags=re.IGNORECASE)
    # Remove trailing "?" patterns
    text = re.sub(r'\s+\?\.?$', '.', text)
    text = re.sub(r'\s+\?\s+', ' ', text)
    # Collapse double spaces
    text = re.sub(r'\s{2,}', ' ', text).strip()
    # If body became empty or just punctuation, provide default
    if not text or text in ('.', '_No body text_'):
        clean_event = event_type.replace('.', ' ') if event_type else 'event'
        text = f'A {clean_event} event occurred.'
    return text


def _parse_response(db_rows: List[Dict]) -> Dict:
    """
    Extract the SP response from database rows.
    The notifications SP returns data under the 'sp_notifications' key
    (not 'result' as in other CRM agents).
    """
    if not db_rows:
        return {}
    first = db_rows[0]
    # Primary: sp_notifications key (set in SQL as alias)
    val = first.get('sp_notifications')
    if val is not None:
        if isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        elif isinstance(val, dict):
            return val
    # Fallback: result key (legacy / psycopg2 normalisation)
    val = first.get('result')
    if val is not None:
        if isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                pass
        elif isinstance(val, dict):
            return val
    # Last resort: treat first row as response if it has recognisable keys
    if any(k in first for k in ('notifications', 'unread_count', 'hash', 'notification_uuid')):
        return first
    return first


# ============================================================================
# PUBLIC API
# ============================================================================

def format_response(db_rows: List[Dict], params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format sp_notifications DB rows into the output dict expected by main.py.

    Returns dict with keys:
      output  — formatted markdown string with embedded frontend markers
      mode    — SP mode string
      success — bool
    """
    mode     = str(params.get('mode') or 'unknown').lower().strip()
    response = _parse_response(db_rows)

    logger.info(f'Format Response (sp_notifications v2.6) — mode={mode}')

    out: List[str] = []
    out.append(f'### {_mode_name(mode)}')
    out.append(f'**Time:** {_fmt_dt(datetime.utcnow().isoformat())}')
    out.append('')

    # ── list ─────────────────────────────────────────────────────────────────
    if mode == 'list':
        notifications = response.get('notifications') or []
        employee_name = response.get('employee_name') or 'All Employees'

        out.append(f'**Employee:** {employee_name}')
        out.append('')

        if not notifications:
            out.append('**🎉 No notifications found!**')
        else:
            # ENHANCED: "Read / Unread" toggle column + Inspect column
            out.append('| Icon | Title | Employee | Status | Created | Read / Unread | Inspect |')
            out.append('|------|--------|----------|---------|----------|---------------|----------|')

            for n in notifications:
                icon    = _event_icon(n.get('event_type') or '')
                title   = n.get('title') or 'Untitled'
                created = _fmt_dt(n.get('created_at'))

                # Determine read/unread status
                status     = n.get('status') or ''
                is_unread  = status in ('pending', 'sent', 'unread')
                status_txt = '**🟢 Unread**' if is_unread else 'Read'

                emp_uuid   = n.get('employee_uuid') or '—'

                # Toggle marker: [TOGGLE:notification_uuid:status:employee_uuid]
                toggle_status = 'unread' if is_unread else 'read'
                notif_uuid    = n.get('notification_uuid') or ''
                toggle        = f'[TOGGLE:{notif_uuid}:{toggle_status}:{n.get("employee_uuid") or ""}]'

                inspect = f'[INSPECT:{notif_uuid}]'

                out.append(
                    f'| {icon} | **{title}** | {emp_uuid} | {status_txt} | '
                    f'{created} | {toggle} | {inspect} |'
                )

        # Action bar replaces standard footer for list mode
        out.append('')
        out.append('[ACTIONBAR]')

    # ── unread_count ──────────────────────────────────────────────────────────
    elif mode == 'unread_count':
        out.append(f'**Unread Notifications:** {response.get("unread_count", 0)}')
        out.extend(STANDARD_FOOTER)

    # ── poll ──────────────────────────────────────────────────────────────────
    elif mode == 'poll':
        out.append('**Real-Time Polling Result**')
        out.append('')
        out.append('| Field | Value |')
        out.append('|--------|--------|')
        out.append(f'| Unread Count | {response.get("unread_count", 0)} |')
        out.append(f'| Hash | `{response.get("hash") or "N/A"}` |')
        out.extend(STANDARD_FOOTER)

    # ── click ─────────────────────────────────────────────────────────────────
    elif mode == 'click':
        nav = response.get('navigate') or {}
        out.append('**Notification Opened**')
        out.append('')
        out.append('| Field | Value |')
        out.append('|--------|--------|')
        out.append(f'| Notification ID | {response.get("notification_uuid") or "N/A"} |')
        out.append(f'| Status | {response.get("status") or "N/A"} |')
        out.append(f'| Entity Type | {nav.get("entity_type") or "N/A"} |')
        out.append(f'| Entity ID | {nav.get("entity_uuid") or "N/A"} |')
        out.append(f'| Event Type | {nav.get("event_type") or "N/A"} |')
        out.extend(STANDARD_FOOTER)

    # ── mark_read ─────────────────────────────────────────────────────────────
    elif mode == 'mark_read':
        out.append('**✅ Notification Marked as Read**')
        out.append('')
        out.append(f'Notification ID: `{response.get("notification_uuid") or "N/A"}`')
        out.extend(STANDARD_FOOTER)

    # ── mark_unread ───────────────────────────────────────────────────────────
    elif mode == 'mark_unread':
        out.append('**✅ Notification Marked as Unread**')
        out.append('')
        out.append(f'Notification ID: `{response.get("notification_uuid") or "N/A"}`')
        out.extend(STANDARD_FOOTER)

    # ── mark_all_read ─────────────────────────────────────────────────────────
    elif mode == 'mark_all_read':
        out.append('**✅ All Notifications Marked as Read**')
        out.append('')
        out.append(f'Updated: **{response.get("updated", 0)}** notifications')
        out.extend(STANDARD_FOOTER)

    # ── mark_all_unread ───────────────────────────────────────────────────────
    elif mode == 'mark_all_unread':
        out.append('**✅ All Notifications Marked as Unread**')
        out.append('')
        out.append(f'Updated: **{response.get("updated", 0)}** notifications')
        out.extend(STANDARD_FOOTER)

    # ── inspect_notification ──────────────────────────────────────────────────
    elif mode == 'inspect_notification':
        template  = response.get('template') or {}
        formatted = response.get('formatted') or {}
        metadata  = (formatted.get('metadata') or {}) if isinstance(formatted, dict) else {}

        event_type  = metadata.get('event_type') or ''
        event_icon  = _event_icon(event_type)

        # Triggered-by employee
        triggered_uuid = metadata.get('triggered_by_employee_uuid')
        triggered_name = _employee_name(triggered_uuid)

        # Clean up template body (remove unresolved '?' placeholders)
        raw_body   = template.get('body') or '_No body text_'
        clean_body = _clean_body(raw_body, event_type)

        # Header: Back to List button
        out.append('[BACKTOLIST]')
        out.append('')
        out.append(f'## {event_icon} Template Preview')
        out.append('')
        out.append(f'**Title:** {template.get("title") or "N/A"}')
        out.append('')
        out.append(clean_body)
        out.append('')

        # Triggered-by employee
        if triggered_name:
            out.append(f'**Triggered by:** {triggered_name}')
            out.append('')
        elif triggered_uuid:
            out.append(f'**Triggered by:** {triggered_uuid}')
            out.append('')

        # Full formatted JSON dump
        out.append('## 🧩 Full Notification JSON')
        out.append('')
        out.append('```json')
        out.append(json.dumps(formatted, indent=2, default=str))
        out.append('```')

        out.extend(STANDARD_FOOTER)

    # ── Fallback ──────────────────────────────────────────────────────────────
    else:
        out.append('Action completed successfully.')
        out.extend(STANDARD_FOOTER)

    return {
        'output':  '\n'.join(out),
        'mode':    mode,
        'success': True,
    }
