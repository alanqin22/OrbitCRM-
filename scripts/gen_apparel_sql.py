"""Regenerate sql/insert_35_apparel.sql from live DB data."""
import psycopg2

outfile = open(r'D:\a\crm_agent\sql\insert_35_apparel.sql', 'w', encoding='utf-8')
conn = psycopg2.connect(host='shinkansen.proxy.rlwy.net', port=26832, dbname='railway',
                        user='postgres', password='SimKpntYtoGdLWdVsXglunQqHZMHXUfQ')
cur = conn.cursor()

def esc(v):
    if v is None:
        return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"

def w(s=''):
    outfile.write(s + '\n')

w('-- ============================================================')
w('-- INSERT 35 best-selling Apparel products + pricing + images')
w('-- Generated: 2026-04-03')
w('-- Products  : 35 rows  (product_number 204-238)')
w('-- Pricing   : 105 rows (Retail + Promo + Wholesale per product)')
w('-- Images    : 175 rows (5 images per product)')
w('-- Category  : Apparel  (7632ef73-7a4a-4320-b5d8-a2bb72bd8c03)')
w('-- Currency  : CAD')
w('-- ============================================================')
w()

# ── SECTION 1: products ───────────────────────────────────────────────────────
cur.execute("""
    SELECT p.product_id, p.product_number, p.product_name, p.sku, p.description,
           p.category_id, p.currency_code, p.stock_quantity,
           p.is_active, p.is_synthetic, p.created_at, p.updated_at
    FROM products p
    JOIN category c ON p.category_id = c.category_id
    WHERE c.category_name = 'Apparel' AND p.product_number >= 204
    ORDER BY p.product_number
""")
products = cur.fetchall()
w('-- ============================================================')
w(f'-- SECTION 1: products ({len(products)} rows)')
w('-- ============================================================')
w()
for row in products:
    pid, num, name, sku, desc, cat, cc, stock, ia, isy, cr, up = row
    ia_s  = 'TRUE' if ia  else 'FALSE'
    isy_s = 'TRUE' if isy else 'FALSE'
    cr_s  = cr.strftime('%Y-%m-%d %H:%M:%S+00')
    up_s  = up.strftime('%Y-%m-%d %H:%M:%S+00')
    w(f'-- [{num}] {name[:72]}')
    w('INSERT INTO products')
    w('  (product_id, product_number, product_name, sku, description,')
    w('   category_id, currency_code, stock_quantity, is_active, is_synthetic, created_at, updated_at)')
    w('VALUES')
    w(f'  ({esc(str(pid))}, {num}, {esc(name)}, {esc(sku)}, {esc(desc)},')
    w(f'   {esc(str(cat))}, {esc(cc)}, {stock}, {ia_s}, {isy_s}, {esc(cr_s)}, {esc(up_s)})')
    w('ON CONFLICT (sku) DO UPDATE SET')
    w('  product_name   = EXCLUDED.product_name,')
    w('  description    = EXCLUDED.description,')
    w('  stock_quantity = EXCLUDED.stock_quantity,')
    w('  updated_at     = EXCLUDED.updated_at;')
    w()

# ── SECTION 2: product_pricing ────────────────────────────────────────────────
cur.execute("""
    SELECT pp.product_pricing_id, pp.product_id, p.sku, p.product_number,
           pp.price_type, pp.price_value, pp.currency_code,
           pp.is_synthetic, pp.created_at, pp.updated_at
    FROM product_pricing pp
    JOIN products p ON pp.product_id = p.product_id
    WHERE p.product_number BETWEEN 204 AND 238
    ORDER BY p.product_number,
             CASE pp.price_type WHEN 'Retail' THEN 1 WHEN 'Promo' THEN 2 ELSE 3 END
""")
pricing = cur.fetchall()
w()
w('-- ============================================================')
w(f'-- SECTION 2: product_pricing ({len(pricing)} rows)')
w('-- ============================================================')
w()
w('DELETE FROM product_pricing')
w('WHERE product_id IN (')
w('  SELECT product_id FROM products WHERE product_number BETWEEN 204 AND 238')
w(');')
w()
for row in pricing:
    ppid, pid, sku, num, ptype, pval, cc, isy, cr, up = row
    isy_s = 'TRUE' if isy else 'FALSE'
    cr_s  = cr.strftime('%Y-%m-%d %H:%M:%S+00')
    up_s  = up.strftime('%Y-%m-%d %H:%M:%S+00')
    w(f'-- [{num}] {sku}  {ptype}: ${pval}')
    w('INSERT INTO product_pricing')
    w('  (product_pricing_id, product_id, price_type, price_value, currency_code,')
    w('   is_synthetic, created_at, updated_at)')
    w('VALUES')
    w(f'  ({esc(str(ppid))}, {esc(str(pid))}, {esc(ptype)}, {pval}, {esc(cc)},')
    w(f'   {isy_s}, {esc(cr_s)}, {esc(up_s)});')
    w()

# ── SECTION 3: product_image ──────────────────────────────────────────────────
cur.execute("""
    SELECT pi.product_image_id, pi.product_id, p.sku, p.product_number,
           pi.image_url, pi.sort_order, pi.alt_text, pi.created_at
    FROM product_image pi
    JOIN products p ON pi.product_id = p.product_id
    WHERE p.product_number BETWEEN 204 AND 238
    ORDER BY p.product_number, pi.sort_order
""")
images = cur.fetchall()
w()
w('-- ============================================================')
w(f'-- SECTION 3: product_image ({len(images)} rows)')
w('-- ============================================================')
w()
w('DELETE FROM product_image')
w('WHERE product_id IN (')
w('  SELECT product_id FROM products WHERE product_number BETWEEN 204 AND 238')
w(');')
w()
for row in images:
    piid, pid, sku, num, url, sort, alt, cr = row
    cr_s = cr.strftime('%Y-%m-%d %H:%M:%S+00')
    w(f'-- [{num}] {sku}  sort={sort}')
    w('INSERT INTO product_image')
    w('  (product_image_id, product_id, image_url, sort_order, alt_text, created_at)')
    w('VALUES')
    w(f'  ({esc(str(piid))}, {esc(str(pid))}, {esc(url)}, {sort}, {esc(alt)}, {esc(cr_s)});')
    w()

conn.close()
outfile.close()
print(f'Written: {len(products)} products, {len(pricing)} pricing, {len(images)} images')
