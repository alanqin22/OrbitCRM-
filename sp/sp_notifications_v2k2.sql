-- ============================================================
-- FIX : Updated stored procedure
-- ============================================================
-- Changes from v2j:
--   1. LIST mode: Replaced fragile UNION ALL + LIMIT 1 employee
--      lookup with a simple direct query. When the employee is
--      not found, it still returns notifications (just shows
--      'Unknown Employee' for the name).
--   2. INSPECT mode: Added templates for all new entity events:
--      contact.created/updated/deleted/status_changed/etc.
--      account.created/updated/deleted/status_changed/etc.
--      product.created/updated/deleted/activated/deactivated/etc.
--   3. Added COALESCE guards so NULL names never break output.
-- ============================================================

-- v2k3 adds p_status / p_date_from / p_date_to — drop the old 7-arg
-- overload so calls with default args stay unambiguous.
DROP FUNCTION IF EXISTS sp_notifications(text, uuid, uuid, int, int, text, text);

CREATE OR REPLACE FUNCTION sp_notifications(
    p_mode text,
    p_employee_uuid uuid DEFAULT NULL,
    p_notification_uuid uuid DEFAULT NULL,
    p_limit int DEFAULT 50,
    p_offset int DEFAULT 0,
    p_module text DEFAULT NULL,
    p_search text DEFAULT NULL,
    p_status text DEFAULT NULL,
    p_date_from date DEFAULT NULL,
    p_date_to date DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    result jsonb;
    notif_row RECORD;
    unread_count int;
    hash text;
    updated_count int;
    template jsonb;
    v_event_type text;
    v_payload jsonb;
    v_employee_name text;
BEGIN

    ----------------------------------------------------------------
    -- NORMALIZE MODULE (UI uses plural, events use singular)
    -- Maps to entity_type column in the events table
    ----------------------------------------------------------------
    p_module := CASE
        WHEN p_module IS NULL THEN NULL
        WHEN lower(p_module) IN ('accounts')      THEN 'account'
        WHEN lower(p_module) IN ('contacts')       THEN 'contact'
        WHEN lower(p_module) IN ('contracts')      THEN 'contract'
        WHEN lower(p_module) IN ('invoices')       THEN 'invoice'
        WHEN lower(p_module) IN ('leads')          THEN 'lead'
        WHEN lower(p_module) IN ('opportunities')  THEN 'opportunity'
        WHEN lower(p_module) IN ('orders')         THEN 'order'
        WHEN lower(p_module) IN ('payments')       THEN 'payment'
        WHEN lower(p_module) IN ('products')       THEN 'product'
        WHEN lower(p_module) IN ('activities')     THEN 'activity'
        ELSE lower(p_module)
    END;

    ----------------------------------------------------------------
    -- NORMALIZE STATUS FILTER (v2k4)
    -- The whole system treats 'pending' / 'sent' / 'unread' as a single
    -- "unread" bucket: unread_count, poll, mark_all_read, the frontend,
    -- and the formatter all test status IN ('pending','sent','unread').
    -- The LIST filter, however, used an exact match on p_status, so a row
    -- written by mark_unread / mark_all_unread (status = 'unread') was
    -- hidden from "show unread" even though it still counted as unread
    -- everywhere else. Collapse the filter input to the same two buckets
    -- so LIST agrees with the rest of the SP. (For the seed data, which
    -- only contains 'pending'/'read', behaviour is unchanged.)
    ----------------------------------------------------------------
    p_status := CASE
        WHEN p_status IS NULL THEN NULL
        WHEN lower(p_status) IN ('unread', 'pending', 'sent', 'unseen', 'new') THEN 'unread'
        WHEN lower(p_status) IN ('read', 'seen', 'opened') THEN 'read'
        ELSE lower(p_status)
    END;

    ----------------------------------------------------------------
    -- MODE: LIST
    ----------------------------------------------------------------
    IF p_mode = 'list' THEN

        ----------------------------------------------------------------
        -- Resolve employee name
        ----------------------------------------------------------------
        IF p_employee_uuid IS NOT NULL THEN
            SELECT COALESCE(e.first_name || ' ' || e.last_name, 'Employee')
            INTO v_employee_name
            FROM employees e
            WHERE e.employee_uuid = p_employee_uuid;

            IF v_employee_name IS NULL THEN
                v_employee_name := 'Employee ' || left(p_employee_uuid::text, 8);
            END IF;
        ELSE
            v_employee_name := 'All Employees';
        END IF;

        ----------------------------------------------------------------
        -- Safe defaults for pagination
        ----------------------------------------------------------------
        p_limit  := COALESCE(p_limit, 50);
        p_offset := COALESCE(p_offset, 0);

        ----------------------------------------------------------------
        -- Return notifications + pagination metadata
        -- Pagination block lets the frontend render Page X of Y / Prev / Next
        -- without making a second COUNT round-trip. limit/offset are echoed
        -- back so the UI can confirm what it asked for.
        ----------------------------------------------------------------
        -- v2: ONE row per event (message). For "All Employees" (p_employee_uuid
        -- NULL) the status is aggregated across the recipient group (unread if ANY
        -- member is unread) and the group is summarised; for a specific employee it
        -- reflects THEIR own read state. notification_uuid returned is the MESSAGE
        -- id (group-addressable by the mark/click modes).
        RETURN (
          WITH base AS (
            SELECT
              m.notification_uuid,
              e.event_type, e.entity_type, e.entity_uuid,
              m.title, m.body, m.created_at, m.metadata,
              (SELECT COUNT(*) FROM notification_recipients r
                 WHERE r.notification_uuid = m.notification_uuid) AS recip_total,
              (SELECT COUNT(*) FROM notification_recipients r
                 WHERE r.notification_uuid = m.notification_uuid AND r.read_at IS NOT NULL) AS recip_read,
              CASE
                WHEN p_employee_uuid IS NOT NULL THEN
                  (SELECT r.status FROM notification_recipients r
                     WHERE r.notification_uuid = m.notification_uuid
                       AND r.employee_uuid = p_employee_uuid LIMIT 1)
                ELSE
                  CASE WHEN EXISTS (SELECT 1 FROM notification_recipients r
                                      WHERE r.notification_uuid = m.notification_uuid
                                        AND lower(r.status) IN ('pending','sent','unread'))
                       THEN 'unread' ELSE 'read' END
              END AS eff_status,
              (SELECT string_agg(DISTINCT COALESCE(o2.first_name||' '||o2.last_name,
                                                   e2.first_name||' '||e2.last_name), ', ')
                 FROM notification_recipients r
                 LEFT JOIN owners o2    ON o2.owner_id      = r.employee_uuid
                 LEFT JOIN employees e2 ON e2.employee_uuid = r.employee_uuid
                 WHERE r.notification_uuid = m.notification_uuid) AS recip_names
            FROM notification_messages m
            JOIN events e ON e.event_uuid = m.event_uuid
            WHERE
              (p_employee_uuid IS NULL OR EXISTS (SELECT 1 FROM notification_recipients r
                  WHERE r.notification_uuid = m.notification_uuid AND r.employee_uuid = p_employee_uuid))
              AND (p_module IS NULL OR e.entity_type ILIKE '%' || p_module || '%')
              AND (p_search IS NULL
                   OR e.event_type ILIKE '%' || p_search || '%'
                   OR e.entity_type ILIKE '%' || p_search || '%'
                   OR m.title ILIKE '%' || p_search || '%'
                   OR m.body ILIKE '%' || p_search || '%'
                   OR m.metadata::text ILIKE '%' || p_search || '%')
              AND (p_date_from IS NULL OR m.created_at::date >= p_date_from)
              AND (p_date_to   IS NULL OR m.created_at::date <= p_date_to)
          ),
          filtered AS (
            SELECT * FROM base
            WHERE (p_status IS NULL
                   OR (p_status = 'unread' AND lower(eff_status) IN ('pending','sent','unread'))
                   OR (p_status = 'read'   AND lower(eff_status) = 'read')
                   OR (p_status NOT IN ('unread','read') AND lower(eff_status) = p_status))
          )
          SELECT jsonb_build_object(
            'employee_uuid', p_employee_uuid,
            'employee_name', v_employee_name,
            'pagination', jsonb_build_object(
                'limit', p_limit, 'offset', p_offset,
                'page', (p_offset / NULLIF(p_limit, 0))::int + 1, 'page_size', p_limit,
                'total_records', (SELECT COUNT(*) FROM filtered),
                'total_pages', CEIL((SELECT COUNT(*) FROM filtered)::numeric / NULLIF(p_limit, 0))::int
            ),
            'notifications', (
                SELECT COALESCE(jsonb_agg(
                    jsonb_build_object(
                        'notification_uuid', x.notification_uuid,
                        'event_type',  x.event_type,
                        'entity_type', x.entity_type,
                        'title',       x.title,
                        -- v2: human headline ("Lead Scored — Omar Haddad") so rows
                        -- read distinctly instead of a generic "lead -> lead.scored".
                        'headline',    initcap(translate(x.event_type, '._', '  '))
                                       || COALESCE(' — ' || (fn_notification_entity_summary(x.entity_type, x.entity_uuid)->>'label'), ''),
                        'body',        x.body,
                        'status',      x.eff_status,
                        'created_at',  x.created_at,
                        'metadata',    x.metadata,
                        'employee_uuid', CASE WHEN p_employee_uuid IS NOT NULL THEN p_employee_uuid ELSE NULL END,
                        'employee_name', CASE WHEN p_employee_uuid IS NOT NULL THEN v_employee_name
                                              ELSE x.recip_total || ' recipient' || CASE WHEN x.recip_total = 1 THEN '' ELSE 's' END
                                                   || CASE WHEN x.recip_read > 0 THEN ' · ' || x.recip_read || ' read' ELSE '' END END,
                        'recipients_total', x.recip_total,
                        'recipients_read',  x.recip_read,
                        'recipients',       x.recip_names
                    ) ORDER BY x.created_at DESC), '[]'::jsonb)
                FROM (SELECT * FROM filtered ORDER BY created_at DESC LIMIT p_limit OFFSET p_offset) x
            )
          )
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: INSPECT NOTIFICATION
    ----------------------------------------------------------------
    IF p_mode = 'inspect_notification' THEN

        -- v2: p_notification_uuid is a MESSAGE id; status is aggregated across the
        -- recipient group (per-person read state lives in notification_recipients).
        SELECT m.notification_uuid, m.event_uuid, e.event_type, e.entity_type, e.entity_uuid,
               m.title, m.body,
               CASE WHEN EXISTS (SELECT 1 FROM notification_recipients r
                                   WHERE r.notification_uuid = m.notification_uuid AND r.read_at IS NULL)
                    THEN 'unread' ELSE 'read' END AS status,
               m.channel, m.created_at,
               NULL::timestamptz AS sent_at,
               NULL::timestamptz AS read_at,
               m.metadata
        INTO notif_row
        FROM notification_messages m
        JOIN events e ON m.event_uuid = e.event_uuid
        WHERE m.notification_uuid = p_notification_uuid
          AND (p_employee_uuid IS NULL OR EXISTS (SELECT 1 FROM notification_recipients r
                  WHERE r.notification_uuid = m.notification_uuid AND r.employee_uuid = p_employee_uuid))
          AND (p_module IS NULL OR e.entity_type = p_module)
          AND (
                p_search IS NULL
                OR e.event_type ILIKE '%' || p_search || '%'
                OR e.entity_type ILIKE '%' || p_search || '%'
                OR m.title ILIKE '%' || p_search || '%'
                OR m.body ILIKE '%' || p_search || '%'
                OR m.metadata::text ILIKE '%' || p_search || '%'
              );

        IF NOT FOUND THEN
            RETURN jsonb_build_object(
                'error', 'Notification not found or filtered out',
                'notification_uuid', p_notification_uuid
            );
        END IF;

        ----------------------------------------------------------------
        -- Resolve payload: new-style notifications nest data under
        -- metadata->'payload', old-style store it directly in metadata.
        ----------------------------------------------------------------
        v_event_type := notif_row.event_type;
        v_payload := CASE
            WHEN notif_row.metadata ? 'payload' THEN notif_row.metadata->'payload'
            ELSE notif_row.metadata
        END;

        ----------------------------------------------------------------
        -- Template rendering
        -- Supports old dot-notation, new underscore-notation,
        -- AND new entity.action events (contact/account/product)
        ----------------------------------------------------------------
        CASE v_event_type

            --------------------------------------------------------
            -- LEAD events
            --------------------------------------------------------
            WHEN 'lead.created', 'lead_created' THEN
                template := jsonb_build_object(
                    'title', 'New Lead Created',
                    'body', COALESCE(v_payload->>'lead_name', 'A lead') || ' was created.'
                );
            WHEN 'lead.assigned', 'lead_assigned' THEN
                template := jsonb_build_object(
                    'title', 'Lead Assigned',
                    'body', 'A lead was assigned to you.'
                );
            WHEN 'lead.converted', 'lead_converted' THEN
                template := jsonb_build_object(
                    'title', 'Lead Converted',
                    'body', COALESCE(v_payload->>'lead_name', 'A lead')
                        || ' was converted to an opportunity.'
                );

            --------------------------------------------------------
            -- OPPORTUNITY events
            --------------------------------------------------------
            WHEN 'opportunity.created', 'opportunity_created' THEN
                template := jsonb_build_object(
                    'title', 'New Opportunity',
                    'body', COALESCE(v_payload->>'opportunity_name', 'Opportunity')
                        || ' created for $' || COALESCE(v_payload->>'amount', '0')
                );
            WHEN 'opportunity.stage_changed', 'opportunity_stage_changed' THEN
                template := jsonb_build_object(
                    'title', 'Stage Updated',
                    'body', 'Opportunity moved from '
                        || COALESCE(v_payload->>'old_stage', '?')
                        || ' to '
                        || COALESCE(v_payload->>'new_stage', '?')
                );
            WHEN 'opportunity.won', 'opportunity_won' THEN
                template := jsonb_build_object(
                    'title', 'Opportunity Won',
                    'body', COALESCE(v_payload->>'opportunity_name', 'Opportunity')
                        || ' was closed won for $' || COALESCE(v_payload->>'amount', '0')
                );
            WHEN 'opportunity.lost', 'opportunity_lost' THEN
                template := jsonb_build_object(
                    'title', 'Opportunity Lost',
                    'body', COALESCE(v_payload->>'opportunity_name', 'Opportunity')
                        || ' was closed lost.'
                );

            --------------------------------------------------------
            -- INVOICE events (old dot-notation)
            --------------------------------------------------------
            WHEN 'invoice.created' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Created',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' created for $'
                        || COALESCE(v_payload->>'invoice_amount', COALESCE(v_payload->>'total_amount', '0'))
                );
            WHEN 'invoice.overdue' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Overdue',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' is '
                        || COALESCE(v_payload->>'days_overdue', '0')
                        || ' days overdue.'
                );
            WHEN 'invoice.paid' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Paid',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' has been paid in full.'
                );

            --------------------------------------------------------
            -- INVOICE events (new underscore-notation)
            --------------------------------------------------------
            WHEN 'invoice_created' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Created',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' created for $'
                        || COALESCE(v_payload->>'total_amount', COALESCE(v_payload->>'invoice_amount', '0'))
                );
            WHEN 'invoice_updated' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Updated',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' has been updated. Status: '
                        || COALESCE(v_payload->>'status', '?')
                        || '.'
                );
            WHEN 'invoice_paid' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Paid',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' has been paid in full.'
                );
            WHEN 'invoice_partial' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Partially Paid',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' has been partially paid.'
                );
            WHEN 'invoice_overdue' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Overdue',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' is overdue.'
                );
            WHEN 'invoice_cancelled' THEN
                template := jsonb_build_object(
                    'title', 'Invoice Cancelled',
                    'body', 'Invoice '
                        || COALESCE(v_payload->>'invoice_number', '?')
                        || ' has been cancelled.'
                );

            --------------------------------------------------------
            -- ORDER events (old dot-notation)
            --------------------------------------------------------
            WHEN 'order.status_changed' THEN
                template := jsonb_build_object(
                    'title', 'Order Status Changed',
                    'body', 'Order '
                        || COALESCE(v_payload->>'order_number', '?')
                        || ' status changed to '
                        || COALESCE(v_payload->>'new_status', COALESCE(v_payload->>'status', '?'))
                        || '.'
                );

            --------------------------------------------------------
            -- ORDER events (new underscore-notation)
            --------------------------------------------------------
            WHEN 'order_created' THEN
                template := jsonb_build_object(
                    'title', 'Order Created',
                    'body', 'Order '
                        || COALESCE(v_payload->>'order_number', COALESCE(v_payload->>'order_id', '?'))
                        || ' has been created. Total: $'
                        || COALESCE(v_payload->>'total_amount', '0')
                        || '.'
                );
            WHEN 'order_updated' THEN
                template := jsonb_build_object(
                    'title', 'Order Updated',
                    'body', 'Order '
                        || COALESCE(v_payload->>'order_number', COALESCE(v_payload->>'order_id', '?'))
                        || ' has been updated. Status: '
                        || COALESCE(v_payload->>'status', '?')
                        || '.'
                );
            WHEN 'order_ready' THEN
                template := jsonb_build_object(
                    'title', 'Order Ready',
                    'body', 'Order '
                        || COALESCE(v_payload->>'order_number', COALESCE(v_payload->>'order_id', '?'))
                        || ' is ready.'
                );

            --------------------------------------------------------
            -- PAYMENT events (old dot-notation)
            --------------------------------------------------------
            WHEN 'payment.received' THEN
                template := jsonb_build_object(
                    'title', 'Payment Received',
                    'body', 'Payment of $'
                        || COALESCE(v_payload->>'amount', '0')
                        || ' received.'
                );
            WHEN 'payment.failed' THEN
                template := jsonb_build_object(
                    'title', 'Payment Failed',
                    'body', 'Payment of $'
                        || COALESCE(v_payload->>'amount', '0')
                        || ' failed.'
                );

            --------------------------------------------------------
            -- PAYMENT events (new underscore-notation)
            --------------------------------------------------------
            WHEN 'payment_created' THEN
                template := jsonb_build_object(
                    'title', 'Payment Created',
                    'body', 'Payment of $'
                        || COALESCE(v_payload->>'amount', '0')
                        || ' has been recorded. Status: '
                        || COALESCE(v_payload->>'status', '?')
                        || '.'
                );
            WHEN 'payment_updated' THEN
                template := jsonb_build_object(
                    'title', 'Payment Updated',
                    'body', 'Payment of $'
                        || COALESCE(v_payload->>'amount', '0')
                        || ' has been updated. Status: '
                        || COALESCE(v_payload->>'status', '?')
                        || '.'
                );
            WHEN 'payment_deleted' THEN
                template := jsonb_build_object(
                    'title', 'Payment Deleted',
                    'body', 'A payment of $'
                        || COALESCE(v_payload->>'amount', '0')
                        || ' has been deleted.'
                );

            --------------------------------------------------------
            -- ACTIVITY events
            --------------------------------------------------------
            WHEN 'activity.completed', 'activity_completed' THEN
                template := jsonb_build_object(
                    'title', 'Activity Completed',
                    'body', COALESCE(v_payload->>'activity_name', 'Activity')
                        || ' was completed.'
                );
            WHEN 'activity.due', 'activity_due' THEN
                template := jsonb_build_object(
                    'title', 'Activity Due',
                    'body', COALESCE(v_payload->>'activity_name', 'Activity')
                        || ' is due soon.'
                );

            --------------------------------------------------------
            -- CONTRACT events
            --------------------------------------------------------
            WHEN 'contract.sent', 'contract_sent' THEN
                template := jsonb_build_object(
                    'title', 'Contract Sent',
                    'body', 'Contract '
                        || COALESCE(v_payload->>'contract_number', '?')
                        || ' sent to '
                        || COALESCE(v_payload->>'party_name', '?')
                        || '.'
                );
            WHEN 'contract.viewed', 'contract_viewed' THEN
                template := jsonb_build_object(
                    'title', 'Contract Viewed',
                    'body', 'Contract '
                        || COALESCE(v_payload->>'contract_number', '?')
                        || ' was viewed by '
                        || COALESCE(v_payload->>'party_name', '?')
                        || '.'
                );
            WHEN 'contract.signed', 'contract_signed' THEN
                template := jsonb_build_object(
                    'title', 'Contract Signed',
                    'body', 'Contract '
                        || COALESCE(v_payload->>'contract_number', '?')
                        || ' was signed by '
                        || COALESCE(v_payload->>'party_name', '?')
                        || '.'
                );
            WHEN 'contract.rejected', 'contract_rejected' THEN
                template := jsonb_build_object(
                    'title', 'Contract Rejected',
                    'body', 'Contract '
                        || COALESCE(v_payload->>'contract_number', '?')
                        || ' was rejected by '
                        || COALESCE(v_payload->>'party_name', '?')
                        || '.'
                );
            WHEN 'contract.expired', 'contract_expired' THEN
                template := jsonb_build_object(
                    'title', 'Contract Expired',
                    'body', 'Contract '
                        || COALESCE(v_payload->>'contract_number', '?')
                        || ' has expired.'
                );

            --------------------------------------------------------
            -- CONTACT events (NEW)
            --------------------------------------------------------
            WHEN 'contact.created' THEN
                template := jsonb_build_object(
                    'title', 'New Contact Created',
                    'body', COALESCE(
                            v_payload->'after'->>'first_name',
                            v_payload->>'first_name',
                            ''
                        ) || ' '
                        || COALESCE(
                            v_payload->'after'->>'last_name',
                            v_payload->>'last_name',
                            'A contact'
                        )
                        || ' was created.'
                );
            WHEN 'contact.updated' THEN
                template := jsonb_build_object(
                    'title', 'Contact Updated',
                    'body', COALESCE(
                            v_payload->'after'->>'first_name',
                            v_payload->>'first_name',
                            ''
                        ) || ' '
                        || COALESCE(
                            v_payload->'after'->>'last_name',
                            v_payload->>'last_name',
                            'A contact'
                        )
                        || ' was updated.'
                );
            WHEN 'contact.deleted' THEN
                template := jsonb_build_object(
                    'title', 'Contact Deleted',
                    'body', COALESCE(
                            v_payload->'before'->>'first_name',
                            v_payload->>'first_name',
                            ''
                        ) || ' '
                        || COALESCE(
                            v_payload->'before'->>'last_name',
                            v_payload->>'last_name',
                            'A contact'
                        )
                        || ' was deleted.'
                );
            WHEN 'contact.status_changed' THEN
                template := jsonb_build_object(
                    'title', 'Contact Status Changed',
                    'body', COALESCE(
                            v_payload->'after'->>'first_name',
                            ''
                        ) || ' '
                        || COALESCE(
                            v_payload->'after'->>'last_name',
                            'A contact'
                        )
                        || ' status changed to '
                        || COALESCE(
                            v_payload->'diff'->'status'->>'new',
                            v_payload->'after'->>'status',
                            '?'
                        )
                        || '.'
                );
            WHEN 'contact.email_verified' THEN
                template := jsonb_build_object(
                    'title', 'Contact Email Verified',
                    'body', COALESCE(
                            v_payload->'after'->>'email',
                            'An email'
                        )
                        || ' has been verified.'
                );
            WHEN 'contact.account_changed' THEN
                template := jsonb_build_object(
                    'title', 'Contact Moved to New Account',
                    'body', COALESCE(
                            v_payload->'after'->>'first_name',
                            ''
                        ) || ' '
                        || COALESCE(
                            v_payload->'after'->>'last_name',
                            'A contact'
                        )
                        || ' was moved to a different account.'
                );
            WHEN 'contact.owner_changed' THEN
                template := jsonb_build_object(
                    'title', 'Contact Ownership Changed',
                    'body', COALESCE(
                            v_payload->'after'->>'first_name',
                            ''
                        ) || ' '
                        || COALESCE(
                            v_payload->'after'->>'last_name',
                            'A contact'
                        )
                        || ' was reassigned to a new owner.'
                );

            --------------------------------------------------------
            -- ACCOUNT events (NEW)
            --------------------------------------------------------
            WHEN 'account.created' THEN
                template := jsonb_build_object(
                    'title', 'New Account Created',
                    'body', COALESCE(
                            v_payload->'after'->>'account_name',
                            v_payload->>'account_name',
                            'An account'
                        )
                        || ' was created.'
                );
            WHEN 'account.updated' THEN
                template := jsonb_build_object(
                    'title', 'Account Updated',
                    'body', COALESCE(
                            v_payload->'after'->>'account_name',
                            v_payload->>'account_name',
                            'An account'
                        )
                        || ' was updated.'
                );
            WHEN 'account.deleted' THEN
                template := jsonb_build_object(
                    'title', 'Account Deleted',
                    'body', COALESCE(
                            v_payload->'before'->>'account_name',
                            v_payload->>'account_name',
                            'An account'
                        )
                        || ' was deleted.'
                );
            WHEN 'account.status_changed' THEN
                template := jsonb_build_object(
                    'title', 'Account Status Changed',
                    'body', COALESCE(
                            v_payload->'after'->>'account_name',
                            'An account'
                        )
                        || ' status changed to '
                        || COALESCE(
                            v_payload->'diff'->'status'->>'new',
                            v_payload->'after'->>'status',
                            '?'
                        )
                        || '.'
                );
            WHEN 'account.owner_changed' THEN
                template := jsonb_build_object(
                    'title', 'Account Ownership Changed',
                    'body', COALESCE(
                            v_payload->'after'->>'account_name',
                            'An account'
                        )
                        || ' was reassigned to a new owner.'
                );

            --------------------------------------------------------
            -- PRODUCT events (NEW)
            --------------------------------------------------------
            WHEN 'product.created' THEN
                template := jsonb_build_object(
                    'title', 'New Product Created',
                    'body', COALESCE(
                            v_payload->'after'->>'product_name',
                            v_payload->>'product_name',
                            'A product'
                        )
                        || ' (SKU: '
                        || COALESCE(
                            v_payload->'after'->>'sku',
                            v_payload->>'sku',
                            '?'
                        )
                        || ') was created.'
                );
            WHEN 'product.updated' THEN
                template := jsonb_build_object(
                    'title', 'Product Updated',
                    'body', COALESCE(
                            v_payload->'after'->>'product_name',
                            v_payload->>'product_name',
                            'A product'
                        )
                        || ' was updated.'
                );
            WHEN 'product.deleted' THEN
                template := jsonb_build_object(
                    'title', 'Product Deleted',
                    'body', COALESCE(
                            v_payload->'before'->>'product_name',
                            v_payload->>'product_name',
                            'A product'
                        )
                        || ' was deleted.'
                );
            WHEN 'product.activated' THEN
                template := jsonb_build_object(
                    'title', 'Product Activated',
                    'body', COALESCE(
                            v_payload->'after'->>'product_name',
                            'A product'
                        )
                        || ' has been activated.'
                );
            WHEN 'product.deactivated' THEN
                template := jsonb_build_object(
                    'title', 'Product Deactivated',
                    'body', COALESCE(
                            v_payload->'after'->>'product_name',
                            'A product'
                        )
                        || ' has been deactivated.'
                );
            WHEN 'product.stock_changed' THEN
                template := jsonb_build_object(
                    'title', 'Stock Level Changed',
                    'body', COALESCE(
                            v_payload->'after'->>'product_name',
                            'A product'
                        )
                        || ' stock changed from '
                        || COALESCE(
                            v_payload->'diff'->'stock_quantity'->>'old',
                            '?'
                        )
                        || ' to '
                        || COALESCE(
                            v_payload->'diff'->'stock_quantity'->>'new',
                            v_payload->'after'->>'stock_quantity',
                            '?'
                        )
                        || '.'
                );

            --------------------------------------------------------
            -- FALLBACK (catch-all for any unhandled event types)
            --------------------------------------------------------
            ELSE
                template := jsonb_build_object(
                    'title', initcap(replace(v_event_type, '_', ' ')),
                    'body', 'Event ' || v_event_type
                        || ' occurred on ' || COALESCE(notif_row.entity_type, 'entity')
                        || '.'
                );
        END CASE;

        RETURN jsonb_build_object(
            'template', template,
            'formatted', jsonb_build_object(
                'notification_uuid', notif_row.notification_uuid,
                'event_uuid', notif_row.event_uuid,
                'event_type', notif_row.event_type,
                'entity_type', notif_row.entity_type,
                'entity_uuid', notif_row.entity_uuid,
                'title', notif_row.title,
                'body', notif_row.body,
                'status', notif_row.status,
                'channel', notif_row.channel,
                'created_at', notif_row.created_at,
                'sent_at', notif_row.sent_at,
                'read_at', notif_row.read_at,
                'metadata', notif_row.metadata,
                -- v2: human-readable headline + resolved entity summary so the
                -- inspector reads as a business event, not UUID soup.
                'headline', initcap(translate(notif_row.event_type, '._', '  '))
                            || COALESCE(' — ' || (fn_notification_entity_summary(notif_row.entity_type, notif_row.entity_uuid)->>'label'), ''),
                'entity_summary', fn_notification_entity_summary(notif_row.entity_type, notif_row.entity_uuid)
            )
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: POLL
    ----------------------------------------------------------------
    IF p_mode = 'poll' THEN
        -- v2: count DISTINCT unread messages (one per event) with an unread recipient
        SELECT COUNT(*) INTO unread_count
        FROM notification_messages m JOIN events e ON e.event_uuid = m.event_uuid
        WHERE EXISTS (SELECT 1 FROM notification_recipients r
                      WHERE r.notification_uuid = m.notification_uuid AND r.read_at IS NULL
                        AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid))
          AND (p_module IS NULL OR e.entity_type = p_module)
          AND (p_search IS NULL
               OR e.event_type ILIKE '%' || p_search || '%'
               OR e.entity_type ILIKE '%' || p_search || '%'
               OR m.title ILIKE '%' || p_search || '%'
               OR m.body ILIKE '%' || p_search || '%'
               OR m.metadata::text ILIKE '%' || p_search || '%');

        SELECT md5(
            COALESCE(MAX(r.read_at)::text, '') ||
            COALESCE(MAX(r.created_at)::text, '') ||
            unread_count::text || COUNT(*)::text
        ) INTO hash
        FROM notification_recipients r
        WHERE (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid);

        RETURN jsonb_build_object(
            'employee_uuid', p_employee_uuid,
            'unread_count', unread_count,
            'hash', hash
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: CLICK
    ----------------------------------------------------------------
    IF p_mode = 'click' THEN
        -- v2: p_notification_uuid is a MESSAGE id. Read on a group row marks the
        -- whole group read; in a specific employee's inbox it marks only theirs.
        UPDATE notification_recipients r
           SET status = 'read', read_at = now()
         WHERE r.notification_uuid = p_notification_uuid
           AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid)
           AND r.read_at IS NULL;

        RETURN (
            SELECT jsonb_build_object(
                'notification_uuid', m.notification_uuid,
                'status', 'read',
                'navigate', m.metadata
            )
            FROM notification_messages m
            WHERE m.notification_uuid = p_notification_uuid
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: UNREAD COUNT
    ----------------------------------------------------------------
    IF p_mode = 'unread_count' THEN
        -- v2: DISTINCT unread messages (one per event) with an unread recipient
        RETURN (
            SELECT jsonb_build_object(
                'employee_uuid', p_employee_uuid,
                'unread_count', COUNT(*)
            )
            FROM notification_messages m JOIN events e ON e.event_uuid = m.event_uuid
            WHERE EXISTS (SELECT 1 FROM notification_recipients r
                          WHERE r.notification_uuid = m.notification_uuid AND r.read_at IS NULL
                            AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid))
              AND (p_module IS NULL OR e.entity_type = p_module)
              AND (p_search IS NULL
                    OR e.event_type ILIKE '%' || p_search || '%'
                    OR e.entity_type ILIKE '%' || p_search || '%'
                    OR m.title ILIKE '%' || p_search || '%'
                    OR m.body ILIKE '%' || p_search || '%'
                    OR m.metadata::text ILIKE '%' || p_search || '%')
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: MARK READ
    ----------------------------------------------------------------
    IF p_mode = 'mark_read' THEN
        UPDATE notification_recipients r
           SET status = 'read', read_at = COALESCE(r.read_at, now())
         WHERE r.notification_uuid = p_notification_uuid
           AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid);

        RETURN jsonb_build_object(
            'notification_uuid', p_notification_uuid,
            'status', 'read'
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: MARK UNREAD
    ----------------------------------------------------------------
    IF p_mode = 'mark_unread' THEN
        UPDATE notification_recipients r
           SET status = 'unread'   -- read_at intentionally NOT cleared (audit)
         WHERE r.notification_uuid = p_notification_uuid
           AND (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid);

        RETURN jsonb_build_object(
            'notification_uuid', p_notification_uuid,
            'status', 'unread'
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: MARK ALL READ
    ----------------------------------------------------------------
    IF p_mode = 'mark_all_read' THEN
        UPDATE notification_recipients r
           SET status = 'read', read_at = now()
         WHERE (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid)
           AND r.read_at IS NULL;

        GET DIAGNOSTICS updated_count = ROW_COUNT;

        RETURN jsonb_build_object(
            'employee_uuid', p_employee_uuid,
            'updated', updated_count
        );
    END IF;

    ----------------------------------------------------------------
    -- MODE: MARK ALL UNREAD
    ----------------------------------------------------------------
    IF p_mode = 'mark_all_unread' THEN
        UPDATE notification_recipients r
           SET status = 'unread'   -- read_at preserved (audit)
         WHERE (p_employee_uuid IS NULL OR r.employee_uuid = p_employee_uuid)
           AND r.status = 'read';

        GET DIAGNOSTICS updated_count = ROW_COUNT;

        RETURN jsonb_build_object(
            'employee_uuid', p_employee_uuid,
            'updated', updated_count
        );
    END IF;

    ----------------------------------------------------------------
    -- UNKNOWN MODE
    ----------------------------------------------------------------
    RETURN jsonb_build_object(
        'error', 'Unknown mode',
        'mode', p_mode
    );

END;
$$;
