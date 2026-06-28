-- ============================================================================
-- Executive snapshot — a daily point-in-time record of the briefing metrics so
-- the CEO briefing / dashboard can show CHANGE ("▲1.2% vs yesterday"), trends,
-- and forecast-accuracy history. EAV by design (executive_metric) so AI agents
-- add/retire metrics with ZERO migration as new data sources arrive.
--
-- v1 stores only metrics the briefing already computes from real data; deferred
-- metrics (MRR/ARR, churn, NPS, sentiment, CAC, support) slot in later as rows.
-- ============================================================================
CREATE TABLE IF NOT EXISTS executive_snapshot (
    snapshot_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date date NOT NULL,
    period_type   text NOT NULL DEFAULT 'daily',     -- daily | weekly | monthly
    summary_text  text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (snapshot_date, period_type)
);

CREATE TABLE IF NOT EXISTS executive_metric (
    metric_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id uuid NOT NULL REFERENCES executive_snapshot(snapshot_id) ON DELETE CASCADE,
    metric_key  text NOT NULL,        -- captured_7d, revenue_at_risk, pipeline, ...
    value       numeric,
    unit        text,                 -- usd | count | pct
    delta_abs   numeric,              -- vs the previous snapshot
    delta_pct   numeric,
    importance  int DEFAULT 0,
    UNIQUE (snapshot_id, metric_key)
);

CREATE INDEX IF NOT EXISTS ix_exec_snapshot_date ON executive_snapshot (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS ix_exec_metric_key    ON executive_metric (metric_key);
