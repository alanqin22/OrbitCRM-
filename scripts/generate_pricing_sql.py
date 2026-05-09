"""
Generate UPDATE/INSERT SQL for product_pricing table.

Logic:
- Rows with created_at >= 2026-03-27 are NEW (from update_product_pricing.py run).
- Product IDs that appear ONLY in new rows → INSERT SQL (new products).
- Product IDs that appear in BOTH old and new rows → UPDATE SQL for active rows.

For UPDATE: target existing active rows using product_id + price_type,
where effective_to IS NULL or effective_to > '2026-03-26'.
The new row supplies price_value, price_label, effective_from, effective_to.

Output: sql/update_product_pricing.sql
"""
import csv, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CSV_PATH = r"D:\a\crm_agent\product_pricing dataset"
SQL_OUT  = r"D:\a\crm_agent\sql\update_product_pricing.sql"
CUTOFF   = "2026-03-27"


def esc(s):
    return str(s).replace("'", "''")


def null_or_quote(val):
    """Return SQL NULL or a quoted string."""
    if val in (None, '', 'NULL', 'null'):
        return 'NULL'
    return f"'{esc(val)}'"


def main():
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    new_rows = [r for r in rows if r['created_at'] >= CUTOFF]
    old_rows = [r for r in rows if r['created_at'] < CUTOFF]

    new_pids = set(r['product_id'] for r in new_rows)
    old_pids = set(r['product_id'] for r in old_rows)

    brand_new_pids  = new_pids - old_pids   # INSERT only
    existing_pids   = new_pids & old_pids   # UPDATE

    print(f"New rows (created >= {CUTOFF}): {len(new_rows)}")
    print(f"Old rows:                        {len(old_rows)}")
    print(f"Brand-new product IDs (INSERT):  {len(brand_new_pids)}")
    print(f"Existing product IDs (UPDATE):   {len(existing_pids)}")

    lines = [
        "-- ============================================================",
        "-- product_pricing: UPDATE existing + INSERT new products",
        f"-- Generated: {CUTOFF}",
        "-- ============================================================",
        "",
    ]

    # ── 1. UPDATE existing products ──────────────────────────────────────
    lines += [
        "-- ── 1. UPDATE active price rows for existing products ─────────",
        "-- Targets rows where effective_to IS NULL or effective_to > '2026-03-26'",
        "",
    ]

    update_count = 0
    for pid in sorted(existing_pids):
        pid_new = [r for r in new_rows if r['product_id'] == pid]
        for row in pid_new:
            pt         = row['price_type']
            price_val  = row['price_value']
            eff_from   = row['effective_from']
            eff_to     = null_or_quote(row['effective_to'])
            label      = row['price_label']
            updated_at = row['updated_at']

            lines.append(
                f"-- {pid[:8]}  {pt:<10}  {price_val}"
            )
            lines.append("UPDATE product_pricing")
            lines.append(f"SET   price_value    = {price_val},")
            lines.append(f"      price_label    = '{esc(label)}',")
            lines.append(f"      effective_from = '{eff_from}',")
            lines.append(f"      effective_to   = {eff_to},")
            lines.append(f"      updated_at     = '{updated_at}'")
            lines.append(f"WHERE product_id     = '{pid}'")
            lines.append(f"  AND price_type     = '{pt}'")
            lines.append(
                "  AND (effective_to IS NULL OR effective_to > '2026-03-26');"
            )
            lines.append("")
            update_count += 1

    lines += [
        f"-- Total UPDATE statements: {update_count}",
        "",
        "-- ── 2. INSERT new product price rows ──────────────────────────",
        "",
    ]

    # ── 2. INSERT new products ────────────────────────────────────────────
    insert_count = 0
    for pid in sorted(brand_new_pids):
        pid_rows = [r for r in new_rows if r['product_id'] == pid]
        for row in pid_rows:
            ppid       = row['product_pricing_id']
            pt         = row['price_type']
            price_val  = row['price_value']
            curr       = row['currency_code']
            eff_from   = row['effective_from']
            eff_to     = null_or_quote(row['effective_to'])
            created_at = row['created_at']
            updated_at = row['updated_at']
            label      = row['price_label']
            is_syn     = row['is_synthetic'].upper()  # TRUE / FALSE

            lines.append(
                f"-- {pid[:8]}  {pt:<10}  {price_val}"
            )
            lines.append(
                "INSERT INTO product_pricing"
                " (product_pricing_id, product_id, price_type, price_value,"
                " currency_code, effective_from, effective_to,"
                " created_at, updated_at, price_label, is_synthetic)"
            )
            lines.append(
                f"VALUES ('{ppid}', '{pid}', '{pt}', {price_val},"
                f" '{curr}', '{eff_from}', {eff_to},"
                f" '{created_at}', '{updated_at}', '{esc(label)}', {is_syn})"
            )
            lines.append(
                "ON CONFLICT (product_pricing_id) DO NOTHING;"
            )
            lines.append("")
            insert_count += 1

    lines += [
        f"-- Total INSERT statements: {insert_count}",
        f"-- Total new product IDs:   {len(brand_new_pids)}",
    ]

    sql = "\n".join(lines)
    with open(SQL_OUT, 'w', encoding='utf-8') as f:
        f.write(sql)

    print(f"\nSQL written to: {SQL_OUT}")
    print(f"  UPDATE statements: {update_count}")
    print(f"  INSERT statements: {insert_count}")
    print(f"  New product IDs:   {len(brand_new_pids)}")


if __name__ == "__main__":
    main()
