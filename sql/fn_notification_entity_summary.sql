-- ============================================================================
-- fn_notification_entity_summary(entity_type, entity_uuid) → jsonb
-- Resolves the entity a notification is about into a HUMAN-readable summary so
-- the inspector/list can show "Layla Ibrahim · Score 100" instead of raw UUIDs.
-- Returns NULL when the entity can't be resolved (gone/unknown type) — callers
-- then fall back to the generic title. STABLE; PK lookups only.
-- Shape: { label, sublabel, module, fields:[{label,value}, ...] }
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_notification_entity_summary(p_entity_type text, p_entity_uuid uuid)
RETURNS jsonb
LANGUAGE plpgsql STABLE AS $$
DECLARE r jsonb;
BEGIN
  IF p_entity_uuid IS NULL THEN RETURN NULL; END IF;

  IF lower(p_entity_type) = 'lead' THEN
    SELECT jsonb_build_object(
      'label', NULLIF(trim(coalesce(first_name,'')||' '||coalesce(last_name,'')),''),
      'sublabel', company, 'module', 'lead-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Score','value',score::text),
        jsonb_build_object('label','Rating','value',rating),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Company','value',company),
        jsonb_build_object('label','Email','value',email),
        jsonb_build_object('label','Phone','value',phone)))
    INTO r FROM leads WHERE lead_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'account' THEN
    SELECT jsonb_build_object(
      'label', account_name, 'sublabel', industry, 'module', 'account-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Type','value',type),
        jsonb_build_object('label','Industry','value',industry),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Email','value',email),
        jsonb_build_object('label','Phone','value',phone)))
    INTO r FROM accounts WHERE account_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'contact' THEN
    SELECT jsonb_build_object(
      'label', NULLIF(trim(coalesce(first_name,'')||' '||coalesce(last_name,'')),''),
      'sublabel', role, 'module', 'contact-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Role','value',role),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Email','value',email),
        jsonb_build_object('label','Phone','value',phone)))
    INTO r FROM contacts WHERE contact_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'opportunity' THEN
    SELECT jsonb_build_object(
      'label', name, 'sublabel', stage, 'module', 'opportunity-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Amount','value','$'||to_char(coalesce(amount,0),'FM999,999,990.00')),
        jsonb_build_object('label','Stage','value',stage),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Close Date','value',close_date::text)))
    INTO r FROM opportunities WHERE opportunity_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'order' THEN
    SELECT jsonb_build_object(
      'label', order_number, 'sublabel', status, 'module', 'order-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Total','value','$'||to_char(coalesce(total_amount,0),'FM999,999,990.00')),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Order Date','value',order_date::text)))
    INTO r FROM orders WHERE order_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'invoice' THEN
    SELECT jsonb_build_object(
      'label', invoice_number, 'sublabel', status, 'module', 'accounting-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Amount','value','$'||to_char(coalesce(total_amount,0),'FM999,999,990.00')),
        jsonb_build_object('label','Balance Due','value','$'||to_char(coalesce(balance_due,0),'FM999,999,990.00')),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Due Date','value',due_date::text)))
    INTO r FROM invoices WHERE invoice_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'payment' THEN
    SELECT jsonb_build_object(
      'label', 'Payment '||coalesce(reference_number,''), 'sublabel', payment_method, 'module', 'accounting-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Amount','value','$'||to_char(coalesce(amount,0),'FM999,999,990.00')),
        jsonb_build_object('label','Method','value',payment_method),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Date','value',payment_date::text)))
    INTO r FROM payments WHERE payment_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'product' THEN
    SELECT jsonb_build_object(
      'label', product_name, 'sublabel', sku, 'module', 'product-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','SKU','value',sku),
        jsonb_build_object('label','Stock','value',stock_quantity::text)))
    INTO r FROM products WHERE product_id = p_entity_uuid;

  ELSIF lower(p_entity_type) = 'activity' THEN
    SELECT jsonb_build_object(
      'label', subject, 'sublabel', type, 'module', 'activity-mgmt.html',
      'fields', jsonb_build_array(
        jsonb_build_object('label','Type','value',type),
        jsonb_build_object('label','Status','value',status),
        jsonb_build_object('label','Due','value',due_at::text)))
    INTO r FROM activities WHERE activity_id = p_entity_uuid;
  END IF;

  RETURN r;  -- NULL if entity gone / type unhandled
END $$;
