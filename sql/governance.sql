-- ============================================================================
-- governance.sql  —  Phase 5 (confidence-gating + approval queue)
-- ============================================================================
-- The approval queue: when an agent proposes a WRITE/outbound action whose
-- confidence is medium (not high enough to auto-execute, not low enough to
-- skip), it lands here as 'pending' for a human to approve or reject. Approved
-- actions are executed (re-dispatched via A2A) and the result recorded. Every
-- proposal + decision is auditable. Idempotent (CREATE TABLE IF NOT EXISTS).
-- ============================================================================

CREATE TABLE IF NOT EXISTS action_approvals (
    approval_uuid   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type     text        NOT NULL,           -- A2A intent, e.g. email.send_payment_reminder
    proposed_by     text        NOT NULL,           -- agent that proposed it
    entity_type     text,
    entity_id       uuid,
    params          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    confidence      numeric     NOT NULL DEFAULT 0,
    severity        text,
    status          text        NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|executed|failed
    decided_by      text,
    decided_at      timestamptz,
    decision_reason text,
    result          jsonb,
    executed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_action_approvals_status
    ON action_approvals (status, created_at);

COMMENT ON TABLE action_approvals IS
    'Phase 5 approval queue: medium-confidence write actions await human '
    'approve/reject; approved actions are executed (A2A re-dispatch) and '
    'recorded. Full audit of every proposal and decision.';

SELECT 'action_approvals ready' AS status;
