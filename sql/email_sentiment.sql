-- ============================================================================
-- email_sentiment — per-inbound-email sentiment, scored by the Email agent.
-- Feeds the executive snapshot's customer-voice metric (avg sentiment, 7d).
-- Populates as real inbound mail is processed (no backfill / no fabrication).
-- ============================================================================
CREATE TABLE IF NOT EXISTS email_sentiment (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at  timestamptz NOT NULL DEFAULT now(),
    from_addr    text,
    subject      text,
    score        numeric NOT NULL,        -- -1.0 (negative) .. 1.0 (positive)
    label        text NOT NULL,           -- positive | neutral | negative
    intent       text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_email_sentiment_recv ON email_sentiment (received_at DESC);
