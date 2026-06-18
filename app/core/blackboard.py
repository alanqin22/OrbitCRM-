"""Phase 4 — Shared agent memory ("blackboard").

An entity-keyed store of structured observations. Any agent can `post()` a note
about an entity (account / deal / lead / invoice / contact …); any other agent
can `read()` it. This is the leap from agents that *call* each other to agents
that *understand the same situation* — no duplication, no contradiction.

  • One note per (entity_type, entity_id, author_agent, topic) — re-posting
    upserts (an agent keeps one current note per topic per entity).
  • Optional TTL (`ttl_hours`) so stale context ages out; reads skip expired.
  • Backed by the agent_blackboard table (sql/blackboard.sql).

Used by the agent-bus handlers: the overdue-invoice handler respects a
cross-agent 'dunning_hold' note before dunning, and posts an 'ar_risk' note when
it does; the lead handler posts a 'hot_lead' note. Also exposed via the A2A
capability `account.context`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.database import get_connection

logger = logging.getLogger("blackboard")


def post(entity_type: str, entity_id: str, author_agent: str, topic: str,
         note: Optional[str] = None, value: Optional[Dict[str, Any]] = None,
         confidence: float = 1.0, severity: Optional[str] = None,
         ttl_hours: Optional[int] = None) -> None:
    """Upsert an observation about an entity (one note per author+topic)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_blackboard
                    (entity_type, entity_id, author_agent, topic, note, value,
                     confidence, severity, expires_at)
                VALUES
                    (%(et)s, %(eid)s::uuid, %(au)s, %(tp)s, %(note)s, %(val)s::jsonb,
                     %(cf)s, %(sev)s,
                     CASE WHEN %(ttl)s IS NULL THEN NULL
                          ELSE now() + (%(ttl)s || ' hours')::interval END)
                ON CONFLICT (entity_type, entity_id, author_agent, topic)
                DO UPDATE SET note       = EXCLUDED.note,
                              value      = EXCLUDED.value,
                              confidence = EXCLUDED.confidence,
                              severity   = EXCLUDED.severity,
                              expires_at = EXCLUDED.expires_at,
                              updated_at = now()
                """,
                {"et": entity_type, "eid": str(entity_id), "au": author_agent,
                 "tp": topic, "note": note, "val": json.dumps(value or {}),
                 "cf": confidence, "sev": severity, "ttl": ttl_hours},
            )
        conn.commit()
    finally:
        conn.close()


def read(entity_type: str, entity_id: str,
         topic: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read current (non-expired) notes for an entity, newest first."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT author_agent, topic, note, value, confidence, severity,
                       updated_at, expires_at
                FROM   agent_blackboard
                WHERE  entity_type = %(et)s AND entity_id = %(eid)s::uuid
                  AND  (expires_at IS NULL OR expires_at > now())
                  AND  (%(tp)s IS NULL OR topic = %(tp)s)
                ORDER  BY updated_at DESC
                """,
                {"et": entity_type, "eid": str(entity_id), "tp": topic},
            )
            cols = [d[0] for d in cur.description]
            rows = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
                d["expires_at"] = d["expires_at"].isoformat() if d["expires_at"] else None
                d["confidence"] = float(d["confidence"]) if d["confidence"] is not None else None
                rows.append(d)
            return rows
    finally:
        conn.close()


def context(entity_type: str, entity_id: str) -> Dict[str, Any]:
    """All current notes for an entity, plus a topic→authors index."""
    notes = read(entity_type, entity_id)
    topics: Dict[str, List[str]] = {}
    for n in notes:
        topics.setdefault(n["topic"], []).append(n["author_agent"])
    return {"entity_type": entity_type, "entity_id": str(entity_id),
            "note_count": len(notes), "topics": topics, "notes": notes}


def clear(entity_type: str, entity_id: str, author_agent: Optional[str] = None,
          topic: Optional[str] = None) -> int:
    """Remove notes for an entity (optionally scoped to author/topic). Returns count."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM agent_blackboard
                   WHERE entity_type=%(et)s AND entity_id=%(eid)s::uuid
                     AND (%(au)s IS NULL OR author_agent=%(au)s)
                     AND (%(tp)s IS NULL OR topic=%(tp)s)""",
                {"et": entity_type, "eid": str(entity_id), "au": author_agent, "tp": topic},
            )
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


# ============================================================================
# Endpoints
# ============================================================================

router = APIRouter(tags=["blackboard"])


@router.get("/blackboard/{entity_type}/{entity_id}")
def blackboard_get(entity_type: str, entity_id: str):
    return context(entity_type, entity_id)


class _PostBody(BaseModel):
    entity_type: str
    entity_id: str
    author_agent: str
    topic: str
    note: Optional[str] = None
    value: Optional[Dict[str, Any]] = None
    confidence: float = 1.0
    severity: Optional[str] = None
    ttl_hours: Optional[int] = None


@router.post("/blackboard")
def blackboard_post(body: _PostBody):
    post(body.entity_type, body.entity_id, body.author_agent, body.topic,
         body.note, body.value, body.confidence, body.severity, body.ttl_hours)
    return {"ok": True, **context(body.entity_type, body.entity_id)}
