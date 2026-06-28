-- ============================================================================
-- executives — the human-leadership interface layer for AI agents.
-- AI agents resolve "who owns X / who should be notified about Y" by ROLE here,
-- instead of hardcoding addresses. The CEO briefing reads its recipients from
-- this table (executives with 'ceo_briefing' in notification_categories).
--
-- Pragmatic single table: role_code + start/end dates cover turnover and
-- temporary assignment; the AI-routing columns (notification_categories,
-- approval_authority_limit, auto_email_enabled) make it orchestration data, not
-- just an address book. (A fully-normalized roles/assignments split and a
-- generalized Actor model are future evolutions.)
-- ============================================================================
CREATE TABLE IF NOT EXISTS executives (
    executive_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_uuid             uuid,                         -- optional link to employees
    role_code                 text NOT NULL,                -- CEO, CFO, CRO, COO, CPO, CTO
    full_name                 text NOT NULL,
    title                     text,                         -- Chief Executive Officer
    email                     text NOT NULL,
    phone                     text,
    timezone                  text NOT NULL DEFAULT 'America/New_York',
    notification_categories   text[] NOT NULL DEFAULT '{}', -- {ceo_briefing,revenue_risk,large_deals}
    approval_authority_limit  numeric,                      -- e.g. 50000
    is_active                 boolean NOT NULL DEFAULT true,
    auto_email_enabled        boolean NOT NULL DEFAULT true,
    start_date                date,
    end_date                  date,
    notes                     text,
    created_at                timestamptz NOT NULL DEFAULT now(),
    created_by                uuid,
    updated_at                timestamptz NOT NULL DEFAULT now(),
    updated_by                uuid
);
CREATE INDEX IF NOT EXISTS ix_executives_role   ON executives (role_code) WHERE is_active;
CREATE INDEX IF NOT EXISTS ix_executives_notify ON executives USING gin (notification_categories);

-- Seed the CEO from the prior CEO_BRIEFING_EMAIL (idempotent by email).
INSERT INTO executives (role_code, full_name, title, email, notification_categories,
                        is_active, auto_email_enabled, notes)
SELECT 'CEO', 'Alan Qin', 'Chief Executive Officer', 'alanqin22@hotmail.com',
       ARRAY['ceo_briefing','revenue_risk','large_deals'], true, true,
       'Seeded from CEO_BRIEFING_EMAIL — edit via the Executives console.'
WHERE NOT EXISTS (SELECT 1 FROM executives WHERE lower(email) = lower('alanqin22@hotmail.com'));
