"""
Pipeline hygiene — Orchestrator cooperates with the Opportunity + Activity agents
to clean stale/slipped OPEN deals so "Active Pipeline" reflects reality.

A healthy pipeline is NOT noise, so this never touches on-track deals. It acts
only on opportunities already PAST their close date, in two tiers:

  • DEAD    — past close by > PIPELINE_DEAD_DAYS AND no activity in the same
              window → Opportunity agent marks them closed-lost (reason logged),
              shrinking the pipeline to an accurate figure.
  • SLIPPED — past close but recently worked / only mildly late → Activity agent
              drafts a re-engagement task for the deal's owner (deal kept alive).

The Orchestrator then posts ONE consolidated "stale pipeline" summary (per-owner
breakdown in the body) so the cooperation is visible in one place.

Safe by default (mirrors AGENT_BUS_AUTOSEND / NOTIF_TRIAGE_APPLY):
  PIPELINE_HYGIENE_ENABLED  0  master on/off (scheduled tick is a no-op when 0)
  PIPELINE_HYGIENE_APPLY    0  1 = actually write; else dry-run (return the plan)
  PIPELINE_DEAD_DAYS       30  days past close (and idle) before a deal is "dead"

Idempotent: close-lost is guarded by status='open'; re-engagement tasks are not
re-created within 14 days; one active Orchestrator summary, refreshed not stacked.
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from app.core.database import get_connection

logger = logging.getLogger("pipeline_hygiene")


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


ENABLED   = _flag("PIPELINE_HYGIENE_ENABLED")
APPLY     = _flag("PIPELINE_HYGIENE_APPLY")
DEAD_DAYS = int(os.getenv("PIPELINE_DEAD_DAYS", "30"))

# Service-account actors (employees rows)
OPP_AGENT   = "00000000-0000-0000-0000-000000000004"  # Opportunity Agent
ACT_AGENT   = "00000000-0000-0000-0000-000000000005"  # Activity Agent
ORCH_AGENT  = "00000000-0000-0000-0000-000000000012"  # Orchestrator Agent


def _slipped_deals(cur) -> List[Dict[str, Any]]:
    """All OPEN opportunities past their close date, classified dead vs slipped."""
    cur.execute(
        """
        SELECT o.opportunity_id::text, o.name, o.amount::float8,
               o.owner_id::text, o.account_id::text,
               (CURRENT_DATE - o.close_date) AS days_past,
               ( o.close_date < CURRENT_DATE - (%(dead)s || ' days')::interval
                 AND NOT EXISTS (
                     SELECT 1 FROM activities a
                     WHERE a.related_type='opportunity' AND a.related_id = o.opportunity_id
                       AND a.created_at > now() - (%(dead)s || ' days')::interval) ) AS dead,
               COALESCE(NULLIF(TRIM(w.first_name || ' ' || w.last_name), ''), 'Unassigned') AS owner_name,
               (SELECT ev.event_uuid::text FROM events ev
                 WHERE ev.entity_type='opportunity' AND ev.entity_uuid = o.opportunity_id
                 LIMIT 1) AS anchor
        FROM opportunities o
        LEFT JOIN owners w ON w.owner_id = o.owner_id
        WHERE o.status = 'open' AND o.close_date < CURRENT_DATE
        ORDER BY o.amount DESC
        """,
        {"dead": DEAD_DAYS},
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _close_lost(cur, opp: Dict[str, Any]) -> bool:
    """Opportunity agent marks a dead deal closed-lost (guarded by status='open')."""
    cur.execute(
        """UPDATE opportunities
              SET status='closed_lost', stage='closed_lost', updated_at=now(), updated_by=%s::uuid
            WHERE opportunity_id=%s::uuid AND status='open'""",
        (OPP_AGENT, opp["opportunity_id"]),
    )
    if cur.rowcount == 0:
        return False
    cur.execute(
        """INSERT INTO activities
             (type, status, subject, description, owner_id, related_type, related_id,
              account_id, created_by, created_at, updated_at)
           VALUES ('note','completed', %(subj)s, %(desc)s, %(owner)s, 'opportunity',
                   %(opp)s::uuid, %(acct)s, %(by)s::uuid, now(), now())""",
        {"subj": f"Closed-lost (stale pipeline): {opp['name']}",
         "desc": (f"Auto-closed by the Opportunity agent — {opp['days_past']} days past close "
                  f"with no activity in {DEAD_DAYS} days. Reopen if still live."),
         "owner": opp["owner_id"], "opp": opp["opportunity_id"],
         "acct": opp["account_id"], "by": OPP_AGENT},
    )
    return True


def _reengage(cur, opp: Dict[str, Any]) -> bool:
    """Activity agent drafts a re-engagement task for the owner (idempotent 14d)."""
    cur.execute(
        """SELECT 1 FROM activities
            WHERE related_type='opportunity' AND related_id=%s::uuid
              AND subject ILIKE 'Re-engage:%%'
              AND created_at > now() - interval '14 days' LIMIT 1""",
        (opp["opportunity_id"],),
    )
    if cur.fetchone():
        return False
    cur.execute(
        """INSERT INTO activities
             (type, status, subject, description, due_at, owner_id, related_type,
              related_id, account_id, created_by, created_at, updated_at)
           VALUES ('task','open', %(subj)s, %(desc)s, now() + interval '3 days', %(owner)s,
                   'opportunity', %(opp)s::uuid, %(acct)s, %(by)s::uuid, now(), now())""",
        {"subj": f"Re-engage: {opp['name']}",
         "desc": (f"Slipped {opp['days_past']} days past close date. Re-engage the buyer "
                  f"or re-date / progress the opportunity."),
         "owner": opp["owner_id"], "opp": opp["opportunity_id"],
         "acct": opp["account_id"], "by": ACT_AGENT},
    )
    return True


def _summary_body(closed: List[Dict], reengaged: List[Dict]) -> str:
    c_amt = sum(o["amount"] for o in closed)
    lines = [f"### 🧭 Stale-pipeline sweep — Orchestrator coordination", ""]
    if closed:
        lines.append(f"**Closed-lost {len(closed)} dead deal(s)** (${c_amt:,.0f} removed from pipeline):")
        for o in sorted(closed, key=lambda x: -x["amount"])[:15]:
            lines.append(f"- {o['name']} — ${o['amount']:,.0f} · {o['days_past']}d past close · owner {o['owner_name']}")
        lines.append("")
    if reengaged:
        lines.append(f"**Re-engagement task drafted for {len(reengaged)} slipped deal(s)** (kept in pipeline):")
        for o in sorted(reengaged, key=lambda x: -x["amount"])[:15]:
            lines.append(f"- {o['name']} — ${o['amount']:,.0f} · {o['days_past']}d past close · owner {o['owner_name']}")
        lines.append("")
    lines.append("_Opportunity + Activity agents acted; Orchestrator summarised. "
                 "Dead deals reopen if revived; tasks route to each deal's owner._")
    return "\n".join(lines)


def _post_summary(cur, closed: List[Dict], reengaged: List[Dict], anchor: str) -> None:
    """One active Orchestrator 'pipeline_hygiene' summary — refreshed, not stacked."""
    c_amt = sum(o["amount"] for o in closed)
    title = (f"🧭 Stale-pipeline sweep — {len(closed)} closed-lost (${c_amt:,.0f}), "
             f"{len(reengaged)} re-engaged")
    meta = json.dumps({"kind": "pipeline_hygiene", "source": "pipeline_hygiene",
                       "closed": len(closed), "closed_amount": round(c_amt, 2),
                       "reengaged": len(reengaged)})
    cur.execute(
        """SELECT notification_uuid FROM notifications
            WHERE employee_uuid=%s::uuid AND channel='in_app'
              AND status = ANY(%s) AND metadata->>'kind'='pipeline_hygiene'
            ORDER BY created_at DESC LIMIT 1""",
        (ORCH_AGENT, ["pending", "sent", "unread"]),
    )
    row = cur.fetchone()
    body = _summary_body(closed, reengaged)
    if row:
        cur.execute(
            """UPDATE notifications SET title=%s, body=%s, metadata=%s, created_at=now()
                WHERE notification_uuid=%s""",
            (title, body, meta, row[0]),
        )
    else:
        cur.execute(
            """INSERT INTO notifications
                 (employee_uuid, event_uuid, channel, status, title, body, metadata, created_at)
               VALUES (%s::uuid, %s::uuid, 'in_app', 'pending', %s, %s, %s, now())""",
            (ORCH_AGENT, anchor, title, body, meta),
        )


def run_pipeline_hygiene_tick(force: bool = False, apply: Optional[bool] = None) -> Dict[str, Any]:
    """Sense slipped deals → Opportunity/Activity agents act → Orchestrator summarises.
    force=True runs while gated off; apply overrides PIPELINE_HYGIENE_APPLY for one call."""
    if not ENABLED and not force:
        return {"enabled": False, "skipped": True}
    do_apply = APPLY if apply is None else bool(apply)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            deals = _slipped_deals(cur)
            dead = [d for d in deals if d["dead"]]
            slipped = [d for d in deals if not d["dead"]]
            dead_amt = sum(d["amount"] for d in dead)

            if not do_apply:
                conn.rollback()
                return {"enabled": ENABLED, "apply": False, "dead_days": DEAD_DAYS,
                        "slipped_total": len(deals),
                        "would_close_lost": len(dead), "would_remove_amount": round(dead_amt, 2),
                        "would_reengage": len(slipped),
                        "sample_dead": [f"{d['name']} (${d['amount']:,.0f}, {d['days_past']}d)"
                                        for d in sorted(dead, key=lambda x: -x['amount'])[:5]]}

            closed = [d for d in dead if _close_lost(cur, d)]
            reengaged = [d for d in slipped if _reengage(cur, d)]
            anchor = next((d["anchor"] for d in deals if d.get("anchor")), None)
            if (closed or reengaged) and anchor:
                _post_summary(cur, closed, reengaged, anchor)
            conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error(f"[pipeline_hygiene] tick failed: {exc}", exc_info=True)
        return {"enabled": ENABLED, "apply": do_apply, "error": str(exc)}
    finally:
        conn.close()

    removed = sum(d["amount"] for d in closed)
    logger.info(f"[pipeline_hygiene] tick apply={do_apply} closed_lost={len(closed)} "
                f"(${removed:,.0f}) reengaged={len(reengaged)}")
    return {"enabled": ENABLED, "apply": True, "dead_days": DEAD_DAYS,
            "closed_lost": len(closed), "removed_amount": round(removed, 2),
            "reengaged": len(reengaged),
            "summary_posted": bool((closed or reengaged))}


# ── Admin endpoints ─────────────────────────────────────────────────────────────
router = APIRouter(tags=["pipeline-hygiene"])


@router.get("/pipeline-hygiene/status")
def pipeline_hygiene_status():
    return {"enabled": ENABLED, "apply": APPLY, "dead_days": DEAD_DAYS,
            "policy": "past-close deals: dead (idle) → closed-lost; slipped → re-engage task; "
                      "Orchestrator posts one summary"}


@router.post("/pipeline-hygiene/run-once")
async def pipeline_hygiene_run_once(apply: bool = False):
    """Drive one sweep on demand. Defaults to dry-run (returns the plan); pass
    ?apply=true to actually close-lost dead deals + draft re-engagement tasks."""
    import asyncio
    return await asyncio.to_thread(run_pipeline_hygiene_tick, True, apply)
