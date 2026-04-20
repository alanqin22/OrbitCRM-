"""SQL Query Builder for EmailAgent.

Builds queries for:
  - sp_notifications (event_inbox / heartbeat)
  - email_templates  (list_templates)
  - audit_log        (sent_emails)
  - agent_status     (aggregate counts)
  - sp_leads / sp_contacts / sp_accounts (recipient lookup for send_template)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

EMAIL_AGENT_UUID = '00000000-0000-0000-0000-000000000011'


def build_email_query(params: Dict[str, Any]) -> Tuple[str, dict]:
    """
    Return (sql, debug_info) for the given mode.
    For modes handled outside the DB (imap_inbox, imap_search, send_email,
    send_template), returns ('', {}) — the db_node skips the DB call.
    """
    mode = str(params.get('mode') or '').lower().strip()
    logger.info(f"Building email query for mode='{mode}'")

    if mode == 'event_inbox':
        sql = (
            f"SELECT sp_notifications("
            f"p_mode := 'poll', "
            f"p_module := 'email', "
            f"p_employee_id := '{EMAIL_AGENT_UUID}'"
            f") AS result;"
        )
        return sql, {'mode': mode}

    if mode == 'list_templates':
        sql = (
            "SELECT row_to_json(t) AS result "
            "FROM ("
            "  SELECT template_id, event_type, subject_tpl, is_active, updated_at "
            "  FROM email_templates ORDER BY event_type"
            ") t;"
        )
        return sql, {'mode': mode, 'raw': True}

    if mode == 'sent_emails':
        limit = int(params.get('limit') or 20)
        sql = (
            "SELECT row_to_json(t) AS result "
            "FROM ("
            f"  SELECT entity_id, "
            f"    payload->>'to'         AS \"to\", "
            f"    payload->>'subject'    AS subject, "
            f"    payload->>'event_type' AS event_type, "
            f"    created_at             AS date "
            f"  FROM audit_log "
            f"  WHERE entity = 'email' AND action = 'sent' "
            f"  ORDER BY created_at DESC "
            f"  LIMIT {limit}"
            ") t;"
        )
        return sql, {'mode': mode, 'raw': True}

    if mode == 'agent_status':
        sql = (
            "SELECT row_to_json(t) AS result FROM ("
            "  SELECT "
            "    (SELECT COUNT(*) FROM crm_agent_memory "
            "     WHERE target_agent='EmailAgent' AND resolved=FALSE) AS unresolved_memory, "
            "    (SELECT COUNT(*) FROM audit_log "
            "     WHERE entity='email' AND action='sent' "
            "     AND created_at > now() - interval '24 hours') AS sent_24h, "
            "    (SELECT COUNT(*) FROM event_subscriptions "
            f"    WHERE employee_uuid='{EMAIL_AGENT_UUID}' AND is_enabled=TRUE) AS active_subscriptions"
            ") t;"
        )
        return sql, {'mode': mode, 'raw': True}

    if mode in ('get_lead',):
        entity_id = params.get('entityId', '')
        sql = f"SELECT sp_leads(p_mode := 'get', p_lead_id := '{entity_id}') AS result;"
        return sql, {'mode': mode}

    if mode in ('get_contact',):
        entity_id = params.get('entityId', '')
        sql = f"SELECT sp_contacts(p_mode := 'get', p_contact_id := '{entity_id}') AS result;"
        return sql, {'mode': mode}

    if mode in ('get_account',):
        entity_id = params.get('entityId', '')
        sql = f"SELECT sp_accounts(p_mode := 'get', p_account_id := '{entity_id}') AS result;"
        return sql, {'mode': mode}

    # Modes handled entirely outside the DB (IMAP/SMTP)
    return '', {'mode': mode, 'skip_db': True}
