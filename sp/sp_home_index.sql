-- ============================================================================
-- sp_home_index  v1.1
-- CRM Home Dashboard — four KPI cards in a single round-trip
--
-- Returns one JSONB document with four top-level sections:
--
--   active_pipeline   — open opportunities  (count + total_amount + weighted_amount)
--   open_leads        — leads awaiting qualification (count + by_status breakdown)
--   pending_orders    — orders processing & ready  (count + by_status breakdown)
--   unread_alerts     — unread notifications past 30 days
--                       (count_30d, count_today, count_yesterday, delta_today,
--                        by_day[]  — daily sparkline for the last 30 days)
--
-- OPTIONAL FILTERS (all default NULL → no filter applied):
--   p_owner_id        — scope pipeline + leads to one owner / employee
--   p_employee_uuid   — scope notifications to one employee
--                       (kept separate because leads use UUID "owner_id" while
--                        notifications use UUID "employee_uuid")
--   p_today           — override the "today" date (useful in tests / time-zones)
--
-- USAGE:
--   SELECT sp_home_index();
--   SELECT sp_home_index(p_owner_id := '<uuid>');
--   SELECT sp_home_index(p_employee_uuid := '<uuid>');
--   SELECT sp_home_index(p_owner_id := '<uuid>', p_employee_uuid := '<uuid>');
--
-- SOURCE SPs (data model contracts):
--   sp_opportunities v4e  — opportunities table, status='open'
--   sp_leads v3           — leads table, status NOT IN ('deleted','converted'),
--                           merged_into_lead_id IS NULL
--   sp_orders v5.4        — orders table, LOWER(status) IN ('pending','processing','ready'),
--                           deleted_at IS NULL
--   sp_notifications v2k2 — notifications table JOIN events,
--                           status IN ('pending','sent','unread')  ← "unread" per that SP
-- ============================================================================

DROP FUNCTION IF EXISTS sp_home_index(UUID, UUID, DATE);

CREATE OR REPLACE FUNCTION sp_home_index(
    p_owner_id        UUID   DEFAULT NULL,
    p_employee_uuid   UUID   DEFAULT NULL,
    p_today           DATE   DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE                          -- reads only; no side-effects
AS $$
DECLARE
    -- ── Working variables ────────────────────────────────────────────────────
    v_today             DATE    := COALESCE(p_today, CURRENT_DATE);
    v_yesterday         DATE    := v_today - INTERVAL '1 day';

    -- Active pipeline (opportunities)
    v_pipeline_count    BIGINT          := 0;
    v_pipeline_amount   NUMERIC(18,2)   := 0;
    v_pipeline_weighted NUMERIC(18,2)   := 0;

    -- Open leads
    v_leads_count       BIGINT  := 0;
    v_leads_by_status   JSONB   := '[]'::JSONB;

    -- Pending orders
    v_orders_count      BIGINT  := 0;
    v_orders_by_status  JSONB   := '[]'::JSONB;

    -- Unread alerts (30-day window)
    v_alerts_30d        BIGINT  := 0;   -- total unread in last 30 days
    v_alerts_today      BIGINT  := 0;   -- unread created today
    v_alerts_yesterday  BIGINT  := 0;   -- unread created yesterday
    v_alerts_delta      BIGINT  := 0;   -- today minus yesterday
    v_alerts_by_day     JSONB   := '[]'::JSONB;  -- daily sparkline [{day,count}]

    -- Generated-at timestamp (ISO 8601)
    v_generated_at      TEXT    := TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');

BEGIN
    -- =========================================================================
    -- 1. ACTIVE PIPELINE
    --    Source: opportunities table (sp_opportunities v4e)
    --    Definition: status = 'open'  (matches v_valid_statuses in that SP)
    --    Columns used: opportunity_id, status, amount, probability, owner_id
    -- =========================================================================
    SELECT
        COUNT(*)                                                AS cnt,
        COALESCE(SUM(amount), 0)                               AS total_amount,
        COALESCE(
            SUM(amount * COALESCE(probability, 0) / 100.0), 0
        )                                                       AS weighted_amount
    INTO
        v_pipeline_count,
        v_pipeline_amount,
        v_pipeline_weighted
    FROM opportunities
    WHERE status = 'open'
      AND (p_owner_id IS NULL OR owner_id = p_owner_id);

    -- =========================================================================
    -- 2. OPEN LEADS  (awaiting qualification)
    --    Source: leads table (sp_leads v3)
    --    Definition: status NOT IN ('deleted', 'converted')
    --                AND merged_into_lead_id IS NULL
    --    Returns total count + per-status breakdown (new / contacted / qualified
    --    / … whatever statuses exist) for the sparkline/tooltip on the KPI card.
    -- =========================================================================
    SELECT COUNT(*)
    INTO v_leads_count
    FROM leads
    WHERE NOT COALESCE(is_deleted, FALSE)            -- exclude archived (matches lead list)
      AND merged_into_lead_id IS NULL                -- exclude merged duplicates
      AND status NOT IN ('deleted', 'converted', 'disqualified')  -- open pipeline only
      AND (p_owner_id IS NULL OR owner_id = p_owner_id);

    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object('status', status, 'count', cnt)
            ORDER BY cnt DESC
        ),
        '[]'::JSONB
    )
    INTO v_leads_by_status
    FROM (
        SELECT LOWER(status) AS status, COUNT(*) AS cnt
        FROM leads
        WHERE NOT COALESCE(is_deleted, FALSE)
          AND merged_into_lead_id IS NULL
          AND status NOT IN ('deleted', 'converted', 'disqualified')
          AND (p_owner_id IS NULL OR owner_id = p_owner_id)
        GROUP BY LOWER(status)
    ) sub;

    -- =========================================================================
    -- 3. PENDING ORDERS  (processing & ready)
    --    Source: orders table (sp_orders v5.4)
    --    Definition: LOWER(status) IN ('pending','processing','ready')
    --                AND deleted_at IS NULL  (soft-delete guard from that SP)
    --    LOWER() wrapper makes this case-insensitive — the orders table now
    --    stores status lowercase, but historical Pascal-case rows would still
    --    count if any remain.
    -- =========================================================================
    SELECT COUNT(*)
    INTO v_orders_count
    FROM orders
    WHERE LOWER(status) IN ('pending', 'processing', 'ready')
      AND deleted_at IS NULL;
    -- Note: orders are not scoped by owner/employee on the home card;
    -- the orders module does not have a single "owner_id" column.
    -- Add a JOIN on accounts/employees here if you later add that filter.

    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object('status', status, 'count', cnt)
            ORDER BY
                CASE status
                    WHEN 'pending'    THEN 1
                    WHEN 'processing' THEN 2
                    WHEN 'ready'      THEN 3
                END
        ),
        '[]'::JSONB
    )
    INTO v_orders_by_status
    FROM (
        SELECT LOWER(status) AS status, COUNT(*) AS cnt
        FROM orders
        WHERE LOWER(status) IN ('pending', 'processing', 'ready')
          AND deleted_at IS NULL
        GROUP BY LOWER(status)
    ) sub;

    -- =========================================================================
    -- 4. UNREAD ALERTS  (past 30 days)
    --    Source: notifications JOIN events (sp_notifications v2k2)
    --    "Unread" definition: status IN ('pending','sent')  ← exact match to
    --    the unread_count and poll modes in sp_notifications v2k2.
    --    Window: created_at >= v_today - 30 days  (rolling 30-day window).
    --    We also break out today and yesterday individually so the frontend
    --    can show a "today: N" sub-stat and a +N/-N delta badge.
    --    by_day[] is a 30-entry sparkline sorted oldest → newest.
    -- =========================================================================

    -- Total unread in the past 30 days
    -- "Unread" = status IN ('pending','sent','unread').
    --   pending/sent  → newly delivered, never opened
    --   unread        → manually toggled back to unread via mark_unread / mark_all_unread
    -- The JOIN on events ensures we only count notifications that belong to a
    -- real event (orphaned rows without an event_uuid are excluded).
    -- "Unread" = notifications the user has been notified about but hasn't opened:
    --   sent   → delivered to the user, not yet read
    --   unread → manually toggled back via mark_unread / mark_all_unread
    -- 'pending' is intentionally excluded: those are still in the delivery queue
    -- and have never been presented to the user.
    -- v2: count DISTINCT unread messages (one per event), not per-recipient copies
    SELECT COUNT(*)
    INTO v_alerts_30d
    FROM notification_messages m
    JOIN events e ON e.event_uuid = m.event_uuid
    WHERE m.created_at >= (v_today - INTERVAL '29 days')  -- 30 days inclusive
      AND m.created_at <   v_today + INTERVAL '1 day'
      AND EXISTS (SELECT 1 FROM notification_recipients r
                    WHERE r.notification_uuid = m.notification_uuid
                      AND r.status IN ('pending','sent','unread')
                      AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid));

    -- Today's unread count
    SELECT COUNT(*)
    INTO v_alerts_today
    FROM notification_messages m
    JOIN events e ON e.event_uuid = m.event_uuid
    WHERE m.created_at >= v_today
      AND m.created_at <  v_today + INTERVAL '1 day'
      AND EXISTS (SELECT 1 FROM notification_recipients r
                    WHERE r.notification_uuid = m.notification_uuid
                      AND r.status IN ('pending','sent','unread')
                      AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid));

    -- Yesterday's unread count (for delta badge)
    SELECT COUNT(*)
    INTO v_alerts_yesterday
    FROM notification_messages m
    JOIN events e ON e.event_uuid = m.event_uuid
    WHERE m.created_at >= v_yesterday
      AND m.created_at <  v_today
      AND EXISTS (SELECT 1 FROM notification_recipients r
                    WHERE r.notification_uuid = m.notification_uuid
                      AND r.status IN ('pending','sent','unread')
                      AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid));

    v_alerts_delta := v_alerts_today - v_alerts_yesterday;

    -- Daily sparkline — one row per day for the past 30 days (oldest → newest)
    -- Days with zero notifications are included so the sparkline has 30 points.
    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'day',   TO_CHAR(d.day, 'YYYY-MM-DD'),
                'count', COALESCE(n.cnt, 0)
            )
            ORDER BY d.day ASC
        ),
        '[]'::JSONB
    )
    INTO v_alerts_by_day
    FROM (
        -- Generate every calendar day in the 30-day window
        SELECT generate_series(
            v_today - INTERVAL '29 days',
            v_today,
            INTERVAL '1 day'
        )::DATE AS day
    ) d
    LEFT JOIN (
        SELECT
            m.created_at::DATE AS day,
            COUNT(*)           AS cnt
        FROM notification_messages m
        JOIN events e ON e.event_uuid = m.event_uuid
        WHERE m.created_at >= (v_today - INTERVAL '29 days')
          AND m.created_at <   v_today + INTERVAL '1 day'
          AND EXISTS (SELECT 1 FROM notification_recipients r
                        WHERE r.notification_uuid = m.notification_uuid
                          AND r.status IN ('pending','sent','unread')
                          AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid))
        GROUP BY m.created_at::DATE
    ) n ON n.day = d.day;

    -- =========================================================================
    -- RETURN  — single JSONB document consumed by the home index page
    -- =========================================================================
    RETURN jsonb_build_object(

        'metadata', jsonb_build_object(
            'status',       'success',
            'code',         0,
            'generated_at', v_generated_at,
            'filters', jsonb_build_object(
                'owner_id',       p_owner_id,
                'employee_uuid',  p_employee_uuid,
                'date',           v_today
            )
        ),

        -- ── Card 1: Active pipeline ───────────────────────────────────────
        'active_pipeline', jsonb_build_object(
            'label',           'Active pipeline',
            'sublabel',        'open opportunities',
            'count',           v_pipeline_count,
            'total_amount',    v_pipeline_amount,
            'weighted_amount', v_pipeline_weighted
        ),

        -- ── Card 2: Open leads ────────────────────────────────────────────
        'open_leads', jsonb_build_object(
            'label',     'Open leads',
            'sublabel',  'awaiting qualification',
            'count',     v_leads_count,
            'by_status', v_leads_by_status
        ),

        -- ── Card 3: Pending orders ────────────────────────────────────────
        'pending_orders', jsonb_build_object(
            'label',     'Pending orders',
            'sublabel',  'processing & ready',
            'count',     v_orders_count,
            'by_status', v_orders_by_status
        ),

        -- ── Card 4: Unread alerts ─────────────────────────────────────────
        'unread_alerts', jsonb_build_object(
            'label',     'Unread alerts',
            'sublabel',  'past 30 days',
            'count_30d',    v_alerts_30d,       -- headline number
            'count_today',  v_alerts_today,     -- today sub-stat
            'count_yesterday', v_alerts_yesterday,
            'delta_today',  v_alerts_delta,     -- today minus yesterday (+/-)
            'by_day',       v_alerts_by_day     -- 30-entry sparkline array
        )
    );

EXCEPTION
    WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'metadata', jsonb_build_object(
                'status',  'error',
                'code',    -500,
                'message', SQLERRM
            )
        );
END;
$$;

-- ============================================================================
-- USAGE EXAMPLES
-- ============================================================================

-- 1. All-tenant home page (no filter)
--    SELECT sp_home_index();

-- 2. Filter pipeline + leads to one sales owner
--    SELECT sp_home_index(p_owner_id := 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx');

-- 3. Filter notifications to one employee
--    SELECT sp_home_index(p_employee_uuid := 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx');

-- 4. Both filters active (owner = this user, notifications = same user)
--    SELECT sp_home_index(
--        p_owner_id      := 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
--        p_employee_uuid := 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
--    );

-- 5. Force a specific reference date (for testing / UTC offset scenarios)
--    SELECT sp_home_index(p_today := '2025-03-14');

-- ============================================================================
-- EXPECTED RESPONSE SHAPE
-- ============================================================================
/*
{
  "metadata": {
    "status": "success",
    "code": 0,
    "generated_at": "2025-03-14T18:42:00Z",
    "filters": {
      "owner_id": null,
      "employee_uuid": null,
      "date": "2025-03-14"
    }
  },
  "active_pipeline": {
    "label":           "Active pipeline",
    "sublabel":        "open opportunities",
    "count":           42,
    "total_amount":    1850000.00,
    "weighted_amount":  730500.00
  },
  "open_leads": {
    "label":    "Open leads",
    "sublabel": "awaiting qualification",
    "count":    87,
    "by_status": [
      { "status": "new",       "count": 45 },
      { "status": "contacted", "count": 31 },
      { "status": "qualified", "count": 11 }
    ]
  },
  "pending_orders": {
    "label":    "Pending orders",
    "sublabel": "processing & ready",
    "count":    23,
    "by_status": [
      { "status": "Pending",    "count": 14 },
      { "status": "Processing", "count":  7 },
      { "status": "Ready",      "count":  2 }
    ]
  },
  "unread_alerts": {
    "label":            "Unread alerts",
    "sublabel":         "past 30 days",
    "count_30d":        74,
    "count_today":       6,
    "count_yesterday":  13,
    "delta_today":      -7,
    "by_day": [
      { "day": "2025-02-13", "count": 3 },
      { "day": "2025-02-14", "count": 1 },
      "... 28 more entries ...",
      { "day": "2025-03-14", "count": 6 }
    ]
  }
}
*/
