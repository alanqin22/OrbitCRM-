-- ============================================================================
-- fn_resolve_reference(field_name, uuid) → human name for a foreign-key value.
-- Used to turn payload FK columns (owner_id, account_id, contact_id, …) into
-- readable names in the notification inspector. Returns NULL if not a known
-- reference field or the row is gone. STABLE; PK lookups only.
-- ============================================================================
CREATE OR REPLACE FUNCTION fn_resolve_reference(p_field text, p_uuid uuid)
RETURNS text
LANGUAGE plpgsql STABLE AS $$
DECLARE v text;
BEGIN
  IF p_uuid IS NULL THEN RETURN NULL; END IF;

  CASE lower(p_field)
    WHEN 'owner_id' THEN
      SELECT NULLIF(TRIM(coalesce(first_name,'')||' '||coalesce(last_name,'')),'')
        INTO v FROM owners WHERE owner_id = p_uuid;
    WHEN 'account_id' THEN
      SELECT account_name INTO v FROM accounts WHERE account_id = p_uuid;
    WHEN 'contact_id' THEN
      SELECT NULLIF(TRIM(coalesce(first_name,'')||' '||coalesce(last_name,'')),'')
        INTO v FROM contacts WHERE contact_id = p_uuid;
    WHEN 'lead_id' THEN
      SELECT NULLIF(TRIM(coalesce(first_name,'')||' '||coalesce(last_name,'')),'')
        INTO v FROM leads WHERE lead_id = p_uuid;
    WHEN 'opportunity_id' THEN
      SELECT name INTO v FROM opportunities WHERE opportunity_id = p_uuid;
    WHEN 'product_id' THEN
      SELECT product_name INTO v FROM products WHERE product_id = p_uuid;
    WHEN 'invoice_id' THEN
      SELECT invoice_number INTO v FROM invoices WHERE invoice_id = p_uuid;
    WHEN 'order_id' THEN
      SELECT order_number INTO v FROM orders WHERE order_id = p_uuid;
    WHEN 'employee_uuid', 'created_by', 'updated_by', 'assigned_to' THEN
      SELECT NULLIF(TRIM(coalesce(first_name,'')||' '||coalesce(last_name,'')),'')
        INTO v FROM employees WHERE employee_uuid = p_uuid;
    ELSE
      v := NULL;
  END CASE;

  RETURN v;
END $$;
