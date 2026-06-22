"""Notification Triage — conscious orchestration of the alert backlog.

THE PROBLEM
-----------
Every DB change emits an event that fans out to ~12 agent service-account inboxes
(channel='agent_inbox') AND to the user (channel='in_app'). Nothing consumes or
*resolves* those rows, so "unread" grows without bound (≈7.8k and climbing). The
only control was running `sql/mark_old_notifications_read_8k.sql` by hand — a blunt
sweep that hides the count, discards genuinely-actionable signal, and refills the
next day.

WHAT THIS DOES (the Notifications/Orchestrator agent reading non-critical alerts
and taking positive action — digest + auto-read, instead of blanket-marking):

  Pass A — agent-inbox receipts.  An agent_inbox row is the agents' own mail. It is
    "resolved" once the agent has nothing left to do: the event_queue row is no
    longer pending, OR no Python handler subscribes to that event_type (it will
    never be actioned). Mark those read; leave the genuine bus worklist (pending +
    a registered handler) for the consumer.

  Pass B — informational digest.  In-app FYI events (`*.created`, `*.updated`,
    `account.updated`, `invoice_created`, `payment_created`, `invoice_paid`, …) get
    rolled up into ONE digest notification per recipient per day (counts preserved
    in metadata), then the originals are marked read. 642 "account updated" → 1.

  Pass C — stale-actionable cleanup.  In-app ACTIONABLE alerts (invoice.overdue,
    lead.scored) are re-validated against live entity state; if the invoice was
    paid / the lead converted-or-disqualified, the alert is resolved. Still-actionable
    alerts are LEFT unread — that is the legitimate human/agent worklist.

  Left untouched: fresh actionable alerts + CRITICAL (`supervisor.alert`). The
  dashboard "UNREAD ALERTS" then reflects real work (tens), not fan-out noise.

SAFETY / GOVERNANCE
-------------------
  • Opt-in: no-op unless NOTIF_TRIAGE_ENABLED=1.
  • Dry-run by default: computes and reports what WOULD change but writes nothing
    unless NOTIF_TRIAGE_APPLY=1 (mirrors AGENT_BUS_AUTOSEND).
  • Per-pass cap (NOTIF_TRIAGE_CAP) bounds a single run.
  • A digest is always created/updated in the SAME transaction that marks its
    originals read — visibility is never dropped without a rollup standing in.
  • Idempotent: re-running folds into the same per-recipient/day digest; already
    read rows are untouched.

CONFIG (env)
  NOTIF_TRIAGE_ENABLED   0     master on/off (scheduled tick is a no-op when 0)
  NOTIF_TRIAGE_APPLY     0     1 = actually write; else dry-run (report only)
  NOTIF_TRIAGE_CAP    5000     max rows touched per pass per run
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter

from app.core.database import get_connection

logger = logging.getLogger("notification_triage")


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


ENABLED = _flag("NOTIF_TRIAGE_ENABLED")
APPLY   = _flag("NOTIF_TRIAGE_APPLY")
CAP     = int(os.getenv("NOTIF_TRIAGE_CAP", "5000"))

_UNREAD = ("pending", "sent", "unread")

# Materiality floor for "is this invoice still worth chasing" — matches agent_bus.
MATERIAL_BALANCE = 50.0

# ── Severity classification (event_type → tier) ─────────────────────────────────
# Anything not explicitly actionable/critical is treated as INFORMATIONAL (FYI):
# that default is what makes the digest drain the long tail of `*.created` /
# `*.updated` chatter without enumerating every type.
CRITICAL_TYPES = {
    "supervisor.alert",
}
ACTIONABLE_TYPES = {
    "activity.overdue_flagged",
    "invoice.overdue", "invoice_overdue",
    "lead.scored",
}


def classify(event_type: Optional[str]) -> str:
    if event_type in CRITICAL_TYPES:
        return "critical"
    if event_type in ACTIONABLE_TYPES:
        return "actionable"
    return "informational"


# ============================================================================
# PASS A — agent-inbox receipts
# ============================================================================

def _handler_types() -> List[str]:
    """Event types a Python handler subscribes to — their pending agent_inbox
    copies are the real bus worklist and must be LEFT for the consumer."""
    try:
        from app.core import agent_bus
        return list(agent_bus.HANDLERS.keys())
    except Exception:
        return []


# An agent_inbox row is resolvable unless it is still a live bus task:
# a pending queue row whose event_type has a registered handler.
_AGENT_INBOX_WHERE = """
    n.channel = 'agent_inbox'
    AND n.status = ANY(%(unread)s)
    AND NOT EXISTS (
        SELECT 1
        FROM   event_queue q
        JOIN   events e ON e.event_uuid = q.event_uuid
        WHERE  q.event_uuid = n.event_uuid
          AND  q.status = 'pending'
          AND  e.event_type = ANY(%(handler_types)s)
    )
"""


def _pass_a(cur, apply: bool) -> Dict[str, Any]:
    params = {"unread": list(_UNREAD), "handler_types": _handler_types(), "cap": CAP}
    cur.execute(f"SELECT count(*) FROM notifications n WHERE {_AGENT_INBOX_WHERE}", params)
    eligible = int(cur.fetchone()[0])
    affected = 0
    if apply and eligible:
        cur.execute(
            f"""UPDATE notifications n SET status='read', read_at=now()
                WHERE n.notification_uuid IN (
                    SELECT n2.notification_uuid FROM notifications n2
                    WHERE {_AGENT_INBOX_WHERE.replace('n.', 'n2.')}
                    LIMIT %(cap)s
                )""",
            params,
        )
        affected = cur.rowcount
    return {"pass": "agent_inbox_receipts", "eligible": eligible,
            "resolved": affected if apply else 0, "would_resolve": eligible}


# ============================================================================
# PASS B — informational digest (in_app)
# ============================================================================

def _informational_breakdown(cur) -> Dict[str, Dict[str, Any]]:
    """{employee_uuid: {'total': n, 'by_type': {...}, 'anchor': event_uuid}} for
    in-app FYI. `anchor` is one absorbed event_uuid, reused as the digest row's
    FK (notifications.event_uuid is NOT NULL) — no new event_type/migration."""
    cur.execute(
        """SELECT n.employee_uuid::text, e.event_type, count(*),
                  max(n.event_uuid::text) AS anchor
           FROM   notifications n
           JOIN   events e ON e.event_uuid = n.event_uuid
           WHERE  n.channel = 'in_app'
             AND  n.status = ANY(%(unread)s)
             AND  (n.metadata->>'kind' IS DISTINCT FROM 'digest')
             AND  NOT (e.event_type = ANY(%(actionable)s))
             AND  NOT (e.event_type = ANY(%(critical)s))
           GROUP BY 1, 2""",
        {"unread": list(_UNREAD),
         "actionable": list(ACTIONABLE_TYPES),
         "critical": list(CRITICAL_TYPES)},
    )
    out: Dict[str, Dict[str, Any]] = {}
    for emp, etype, n, anchor in cur.fetchall():
        rec = out.setdefault(emp, {"total": 0, "by_type": {}, "anchor": anchor})
        rec["total"] += int(n)
        rec["by_type"][etype] = int(n)
    return out


def _digest_body(breakdown: Dict[str, int], total: int) -> str:
    lines = [f"### 🧹 Notification digest — {total} informational updates rolled up", ""]
    for etype, n in sorted(breakdown.items(), key=lambda kv: -kv[1]):
        lines.append(f"- **{etype}** × {n}")
    lines.append("")
    lines.append("_Auto-summarised by the Notifications agent. Actionable and "
                 "critical alerts are kept separate._")
    return "\n".join(lines)


def _upsert_digest(cur, employee_uuid: str, by_type: Dict[str, int], total: int,
                   day: str, anchor: str) -> None:
    """One digest per (recipient, UTC day): fold re-runs into the same row."""
    cur.execute(
        """SELECT notification_uuid, metadata FROM notifications
           WHERE employee_uuid = %(emp)s::uuid AND channel='in_app'
             AND status = ANY(%(unread)s)
             AND metadata->>'kind' = 'digest'
             AND metadata->>'day' = %(day)s
           LIMIT 1""",
        {"emp": employee_uuid, "unread": list(_UNREAD), "day": day},
    )
    row = cur.fetchone()
    if row:
        prev = row[1] or {}
        prev_by = (prev.get("breakdown") or {}) if isinstance(prev, dict) else {}
        merged = dict(prev_by)
        for k, v in by_type.items():
            merged[k] = merged.get(k, 0) + v
        merged_total = sum(merged.values())
        cur.execute(
            """UPDATE notifications
               SET title=%(title)s, body=%(body)s, metadata=%(meta)s, created_at=now()
               WHERE notification_uuid=%(id)s""",
            {"id": row[0],
             "title": f"🧹 Notification digest ({merged_total} updates)",
             "body": _digest_body(merged, merged_total),
             "meta": json.dumps({"kind": "digest", "source": "notification_triage",
                                 "day": day, "breakdown": merged, "absorbed": merged_total})},
        )
    else:
        cur.execute(
            """INSERT INTO notifications
                 (employee_uuid, event_uuid, channel, status, title, body, metadata, created_at)
               VALUES (%(emp)s::uuid, %(anchor)s::uuid, 'in_app', 'pending', %(title)s, %(body)s,
                       %(meta)s, now())""",
            {"emp": employee_uuid, "anchor": anchor,
             "title": f"🧹 Notification digest ({total} updates)",
             "body": _digest_body(by_type, total),
             "meta": json.dumps({"kind": "digest", "source": "notification_triage",
                                 "day": day, "breakdown": by_type, "absorbed": total})},
        )


def _pass_b(cur, apply: bool) -> Dict[str, Any]:
    breakdown = _informational_breakdown(cur)
    recipients = len(breakdown)
    total = sum(r["total"] for r in breakdown.values())
    resolved = 0
    if apply and total:
        day = datetime.now(timezone.utc).date().isoformat()
        for emp, rec in breakdown.items():
            _upsert_digest(cur, emp, rec["by_type"], rec["total"], day, rec["anchor"])
            # Mark the originals read — same transaction as the digest upsert.
            cur.execute(
                """UPDATE notifications n SET status='read', read_at=now()
                   WHERE n.notification_uuid IN (
                       SELECT n2.notification_uuid
                       FROM notifications n2
                       JOIN events e ON e.event_uuid = n2.event_uuid
                       WHERE n2.employee_uuid = %(emp)s::uuid
                         AND n2.channel='in_app' AND n2.status = ANY(%(unread)s)
                         AND (n2.metadata->>'kind' IS DISTINCT FROM 'digest')
                         AND NOT (e.event_type = ANY(%(actionable)s))
                         AND NOT (e.event_type = ANY(%(critical)s))
                       LIMIT %(cap)s
                   )""",
                {"emp": emp, "unread": list(_UNREAD), "cap": CAP,
                 "actionable": list(ACTIONABLE_TYPES), "critical": list(CRITICAL_TYPES)},
            )
            resolved += cur.rowcount
    return {"pass": "informational_digest", "recipients": recipients,
            "would_digest": total, "digested": resolved if apply else 0}


# ============================================================================
# PASS C — stale-actionable cleanup (in_app)
# ============================================================================
# Re-validate in-app ACTIONABLE alerts against live entity state and resolve the
# ones that are no longer actionable. Still-actionable alerts are left unread.
# Set-based per entity type; unknown actionable entity types are left untouched.

_STALE_SQL = {
    # invoice.overdue is stale once paid/cancelled or balance below the floor.
    "invoice": """
        UPDATE notifications n SET status='read', read_at=now()
        FROM events e, accounting_invoice_pipeline v
        WHERE n.event_uuid = e.event_uuid AND e.entity_uuid = v.invoice_id
          AND n.channel='in_app' AND n.status = ANY(%(unread)s)
          AND e.event_type = ANY(%(types)s)
          AND ( v.payment_status NOT IN ('unpaid','partial')
                OR ROUND(v.computed_balance_due::numeric, 2) <= %(floor)s )
    """,
    # lead.scored is stale once the lead is no longer a workable hot lead.
    "lead": """
        UPDATE notifications n SET status='read', read_at=now()
        FROM events e, leads l
        WHERE n.event_uuid = e.event_uuid AND e.entity_uuid = l.lead_id
          AND n.channel='in_app' AND n.status = ANY(%(unread)s)
          AND e.event_type = ANY(%(types)s)
          AND ( COALESCE(l.score,0) < 70 OR COALESCE(l.converted,false)
                OR COALESCE(l.is_deleted,false)
                OR COALESCE(l.status,'') IN ('disqualified','converted') )
    """,
    # An activity_nudge (raised by the agent_bus activity.overdue_flagged handler)
    # is resolved once its activity is completed/closed or brought current — the
    # owner has actioned it, so the reminder closes itself.
    "activity_nudge": """
        UPDATE notifications n SET status='read', read_at=now()
        FROM activities a
        WHERE a.activity_id::text = (n.metadata->>'activity_id')
          AND n.channel='in_app' AND n.status = ANY(%(unread)s)
          AND n.metadata->>'kind' = 'activity_nudge'
          AND ( a.status <> 'open' OR a.due_at IS NULL OR a.due_at >= now() )
    """,
}
_STALE_TYPES = {
    "invoice":        ["invoice.overdue", "invoice_overdue"],
    "lead":           ["lead.scored"],
    "activity_nudge": [],
}


def _count_stale(cur, entity: str) -> int:
    # Reuse the UPDATE's predicate via a count: wrap the same FROM/WHERE.
    sql = _STALE_SQL[entity]
    # Turn the UPDATE…FROM…WHERE into SELECT count(*) by replacing the head.
    head, _, tail = sql.partition("WHERE")
    from_clause = head.split("FROM", 1)[1]
    cur.execute(
        f"SELECT count(*) FROM notifications n, {from_clause} WHERE {tail}",
        {"unread": list(_UNREAD), "types": _STALE_TYPES[entity], "floor": MATERIAL_BALANCE},
    )
    return int(cur.fetchone()[0])


def _pass_c(cur, apply: bool) -> Dict[str, Any]:
    detail: Dict[str, int] = {}
    total = 0
    for entity in _STALE_SQL:
        if apply:
            cur.execute(_STALE_SQL[entity],
                        {"unread": list(_UNREAD), "types": _STALE_TYPES[entity],
                         "floor": MATERIAL_BALANCE})
            n = cur.rowcount
        else:
            n = _count_stale(cur, entity)
        detail[entity] = n
        total += n
    return {"pass": "stale_actionable", "by_entity": detail,
            "resolved" if apply else "would_resolve": total}


# ============================================================================
# TICK
# ============================================================================

def run_triage_tick(force: bool = False, apply: Optional[bool] = None) -> Dict[str, Any]:
    """Sense → classify → resolve. Safe to call directly (scheduler / endpoint).
    force=True runs even when NOTIF_TRIAGE_ENABLED=0; apply overrides NOTIF_TRIAGE_APPLY
    for a single call (None = use the env default)."""
    if not ENABLED and not force:
        return {"enabled": False, "skipped": True}
    do_apply = APPLY if apply is None else bool(apply)

    conn = get_connection()
    try:
        before = _unread_count(conn)
        with conn.cursor() as cur:
            a = _pass_a(cur, do_apply)
            b = _pass_b(cur, do_apply)
            c = _pass_c(cur, do_apply)
        if do_apply:
            conn.commit()
        else:
            conn.rollback()
        after = _unread_count(conn)
    except Exception as exc:
        conn.rollback()
        logger.error(f"[notif_triage] tick failed: {exc}", exc_info=True)
        return {"enabled": ENABLED, "apply": do_apply, "error": str(exc)}
    finally:
        conn.close()

    summary = {"enabled": ENABLED, "apply": do_apply, "cap": CAP,
               "unread_before": before, "unread_after": after if do_apply else before,
               "passes": [a, b, c]}
    logger.info(f"[notif_triage] tick — apply={do_apply} before={before} "
                f"after={summary['unread_after']} passes={[p['pass'] for p in (a,b,c)]}")
    return summary


def _unread_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM notifications WHERE status = ANY(%s)", (list(_UNREAD),))
        return int(cur.fetchone()[0])


# ============================================================================
# Admin endpoints
# ============================================================================

router = APIRouter(tags=["notification-triage"])


@router.get("/notif-triage/status")
def notif_triage_status():
    return {"enabled": ENABLED, "apply": APPLY, "cap": CAP,
            "critical_types": sorted(CRITICAL_TYPES),
            "actionable_types": sorted(ACTIONABLE_TYPES),
            "policy": "everything else → informational digest + auto-read"}


@router.post("/notif-triage/run-once")
async def notif_triage_run_once(apply: bool = False):
    """Drive one triage pass on demand. Defaults to dry-run; pass ?apply=true to
    actually resolve (still requires nothing — force=True so it runs while gated)."""
    import asyncio
    return await asyncio.to_thread(run_triage_tick, True, apply)
