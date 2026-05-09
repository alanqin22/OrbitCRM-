"""
Generate three SQL scripts from live Railway DB data:
  sql/update_products_new.sql
  sql/update_product_images_new.sql
  sql/update_product_pricing_new.sql
"""
import psycopg2
from datetime import datetime

conn = psycopg2.connect(
    host='shinkansen.proxy.rlwy.net', port=26832, dbname='railway',
    user='postgres', password='SimKpntYtoGdLWdVsXglunQqHZMHXUfQ'
)
cur = conn.cursor()

GENERATED = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

NEW_SKUS = (
    'APP-HANE-ECOS-014', 'APP-FRUI-EVER-015',
    'GRO-QUAK-OATS-018', 'GRO-NATU-VALY-019', 'GRO-KELL-SPEC-020',
    'HOME-OXO-BOWL-015',
    'OFF-POST-STIC-019', 'OFF-SCOT-TAPE-020',
    'PC-DOVE-MENS-014',  'PC-HEAD-SHOU-015',
    'SNK-CELS-WILD-014', 'SNK-RXBA-CHOC-015',
    'PET-PURI-PROP-016', 'PET-GREE-ORIG-017',
    'PET-DOG-PUZZ-004',  'PET-DOG-PUZZ-005',   # deactivated
)

def esc(v):
    if v is None:
        return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"

def bool_sql(v):
    return 'TRUE' if v else 'FALSE'

def ts(v):
    if v is None:
        return 'NULL'
    return "'" + str(v) + "'"

# ── Category name lookup ──────────────────────────────────────────────────────
cur.execute('SELECT category_id, category_name FROM category')
cat_names = {str(r[0]): r[1] for r in cur.fetchall()}

# =============================================================================
# 1. products
# =============================================================================
cur.execute('''
    SELECT product_id, product_number, product_name, sku, description,
           category_id, currency_code, stock_quantity, is_active, is_synthetic,
           created_at, updated_at
    FROM products
    WHERE sku = ANY(%s)
    ORDER BY is_active DESC, product_number
''', (list(NEW_SKUS),))
products = cur.fetchall()

lines = [
    '-- ============================================================',
    '-- products table — 14 new products inserted + 2 deactivated',
    f'-- Generated: {GENERATED}',
    '-- Run order: this file first, then images, then pricing',
    '-- ============================================================',
    '',
    '-- ── Step 1: Deactivate replaced Pet Supply products ─────────',
]
for row in products:
    pid, num, name, sku, desc, cat_id, curr, stock, is_active, is_syn, created, updated = row
    if not is_active:
        lines.append(f"UPDATE products")
        lines.append(f"SET    is_active  = FALSE,")
        lines.append(f"       updated_at = {ts(updated)}")
        lines.append(f"WHERE  sku = {esc(sku)};")
        lines.append(f"-- was: {name[:70]}")
        lines.append('')

lines.append('')
lines.append('-- ── Step 2: Insert / upsert 14 new products ────────────────')
lines.append('')

cat_groups = {}
for row in products:
    pid, num, name, sku, desc, cat_id, curr, stock, is_active, is_syn, created, updated = row
    if not is_active:
        continue
    cat = cat_names.get(str(cat_id), str(cat_id))
    cat_groups.setdefault(cat, []).append(row)

for cat, rows in sorted(cat_groups.items()):
    lines.append(f'-- {cat}')
    for row in rows:
        pid, num, name, sku, desc, cat_id, curr, stock, is_active, is_syn, created, updated = row
        lines += [
            f"INSERT INTO products",
            f"    (product_id, product_number, product_name, sku, description,",
            f"     category_id, currency_code, stock_quantity, is_active, is_synthetic,",
            f"     created_at, updated_at)",
            f"VALUES",
            f"    ('{pid}', {num}, {esc(name)}, {esc(sku)},",
            f"     {esc(desc)},",
            f"     '{cat_id}', {esc(curr)}, {stock}, {bool_sql(is_active)}, {bool_sql(is_syn)},",
            f"     {ts(created)}, {ts(updated)})",
            f"ON CONFLICT (sku) DO UPDATE",
            f"    SET product_name    = EXCLUDED.product_name,",
            f"        description     = EXCLUDED.description,",
            f"        stock_quantity  = EXCLUDED.stock_quantity,",
            f"        is_active       = EXCLUDED.is_active,",
            f"        updated_at      = EXCLUDED.updated_at;",
            '',
        ]
    lines.append('')

sql1 = '\n'.join(lines)
with open(r'D:\a\crm_agent\sql\update_products_new.sql', 'w', encoding='utf-8') as f:
    f.write(sql1)
print(f'update_products_new.sql  — {len(products)} rows ({sum(1 for r in products if not r[8])} deactivated, {sum(1 for r in products if r[8])} new)')

# =============================================================================
# 2. product_image
# =============================================================================
cur.execute('''
    SELECT pi.product_image_id, pi.product_id, p.sku, p.product_name,
           pi.image_url, pi.sort_order, pi.alt_text, pi.created_at
    FROM product_image pi
    JOIN products p ON pi.product_id = p.product_id
    WHERE p.sku = ANY(%s)
      AND p.is_active = TRUE
    ORDER BY p.product_number, pi.sort_order
''', (list(NEW_SKUS),))
images = cur.fetchall()

lines = [
    '-- ============================================================',
    '-- product_image table — 5 images × 14 new products = 70 rows',
    f'-- Generated: {GENERATED}',
    '-- Run after update_products_new.sql',
    '-- ============================================================',
    '',
    '-- Wipe existing images for these products first (idempotent re-run)',
    "DELETE FROM product_image",
    "WHERE product_id IN (",
    "    SELECT product_id FROM products WHERE sku = ANY(ARRAY[",
]
sku_list = [r[2] for r in images]
seen = list(dict.fromkeys(sku_list))  # unique, ordered
for i, s in enumerate(seen):
    comma = ',' if i < len(seen) - 1 else ''
    lines.append(f"        '{s}'{comma}")
lines += ["    ])", ");", '']

current_sku = None
for img_id, pid, sku, pname, url, sort, alt, created in images:
    if sku != current_sku:
        current_sku = sku
        lines.append(f'-- {pname[:70]}')
    lines += [
        f"INSERT INTO product_image",
        f"    (product_image_id, product_id, image_url, sort_order, alt_text, created_at)",
        f"VALUES",
        f"    ('{img_id}', '{pid}', {esc(url)}, {sort}, {esc(alt)}, {ts(created)})",
        f"ON CONFLICT (product_id, sort_order)",
        f"DO UPDATE SET image_url = EXCLUDED.image_url, alt_text = EXCLUDED.alt_text;",
        '',
    ]

sql2 = '\n'.join(lines)
with open(r'D:\a\crm_agent\sql\update_product_images_new.sql', 'w', encoding='utf-8') as f:
    f.write(sql2)
print(f'update_product_images_new.sql — {len(images)} rows')

# =============================================================================
# 3. product_pricing
# =============================================================================
cur.execute('''
    SELECT pp.product_pricing_id, pp.product_id, p.sku, p.product_name,
           pp.price_type, pp.price_value, pp.currency_code,
           pp.is_synthetic, pp.created_at, pp.updated_at
    FROM product_pricing pp
    JOIN products p ON pp.product_id = p.product_id
    WHERE p.sku = ANY(%s)
      AND p.is_active = TRUE
    ORDER BY p.product_number, pp.price_type
''', (list(NEW_SKUS),))
pricing = cur.fetchall()

lines = [
    '-- ============================================================',
    '-- product_pricing table — 3 price rows × 14 products = 42 rows',
    f'-- Generated: {GENERATED}',
    '-- price_type values: Retail | Promo | Wholesale',
    '-- Wholesale is 15-25% below Retail; Promo is between Retail and Wholesale',
    '-- Run after update_products_new.sql',
    '-- ============================================================',
    '',
    '-- Wipe existing pricing for these products first (idempotent re-run)',
    "DELETE FROM product_pricing",
    "WHERE product_id IN (",
    "    SELECT product_id FROM products WHERE sku = ANY(ARRAY[",
]
seen_p = list(dict.fromkeys(r[2] for r in pricing))
for i, s in enumerate(seen_p):
    comma = ',' if i < len(seen_p) - 1 else ''
    lines.append(f"        '{s}'{comma}")
lines += ["    ])", ");", '']

# Print a summary table as a comment
lines.append('-- Pricing summary:')
lines.append('-- SKU                        Retail    Promo     Wholesale')
lines.append('-- ' + '-'*60)
sku_prices = {}
for row in pricing:
    ppid, pid, sku, pname, ptype, pval, curr, is_syn, created, updated = row
    sku_prices.setdefault(sku, {})[ptype] = float(pval)
for sku, pts in sku_prices.items():
    r = pts.get('Retail', 0)
    p = pts.get('Promo', 0)
    w = pts.get('Wholesale', 0)
    lines.append(f'-- {sku:28s}  ${r:6.2f}    ${p:6.2f}    ${w:6.2f}')
lines.append('')

current_sku = None
for ppid, pid, sku, pname, ptype, pval, curr, is_syn, created, updated in pricing:
    if sku != current_sku:
        current_sku = sku
        lines.append(f'-- {pname[:70]}')
    lines += [
        f"INSERT INTO product_pricing",
        f"    (product_pricing_id, product_id, price_type, price_value,",
        f"     currency_code, is_synthetic, created_at, updated_at)",
        f"VALUES",
        f"    ('{ppid}', '{pid}', '{ptype}', {float(pval)},",
        f"     '{curr}', {bool_sql(is_syn)}, {ts(created)}, {ts(updated)})",
        f"ON CONFLICT DO NOTHING;",
        '',
    ]

sql3 = '\n'.join(lines)
with open(r'D:\a\crm_agent\sql\update_product_pricing_new.sql', 'w', encoding='utf-8') as f:
    f.write(sql3)
print(f'update_product_pricing_new.sql — {len(pricing)} rows')

conn.close()
print('\nAll 3 SQL files written to sql/')
