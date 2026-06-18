-- ============================================================================
-- blackboard.sql  —  Phase 4 (shared agent memory)
-- ============================================================================
-- An entity-keyed "blackboard": any agent can post a structured observation
-- about an entity (account / deal / lead / invoice / contact …) and any other
-- agent can read it — so agents share SITUATIONAL CONTEXT, not just call each
-- other. One note per (entity, author, topic) — re-posting upserts. Notes can
-- carry a TTL so stale context ages out. Idempotent.
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_blackboard (
    note_uuid     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type   text        NOT NULL,
    entity_id     uuid        NOT NULL,
    author_agent  text        NOT NULL,
    topic         text        NOT NULL,
    note          text,
    value         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    confidence    numeric     NOT NULL DEFAULT 1.0,
    severity      text,                              -- info | warning | critical
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz,                       -- NULL = no expiry
    CONSTRAINT agent_blackboard_uq UNIQUE (entity_type, entity_id, author_agent, topic)
);

CREATE INDEX IF NOT EXISTS idx_blackboard_entity
    ON agent_blackboard (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_blackboard_expires
    ON agent_blackboard (expires_at);

COMMENT ON TABLE agent_blackboard IS
    'Phase 4 shared agent memory: entity-keyed structured observations agents '
    'post and read so they share situational context. Upsert per '
    '(entity_type, entity_id, author_agent, topic); optional TTL via expires_at.';

SELECT 'agent_blackboard ready' AS status;
