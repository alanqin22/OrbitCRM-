"""
Generate two SQL scripts:
  1. update_products.sql  - UPDATE products SET name/sku/description WHERE product_id = ...
  2. insert_products.sql  - INSERT INTO products for image-folder products NOT in the dataset
"""

import csv
import os
import re
import uuid
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
PRODUCT_CSV  = r"D:\a\crm_agent\product dateset.csv"
IMAGE_BASE   = r"D:\a\crm_agent\image"
OUT_UPDATE   = r"D:\a\crm_agent\sql\update_products.sql"
OUT_INSERT   = r"D:\a\crm_agent\sql\insert_products.sql"

CATEGORY_MAP = {
    "7632ef73-7a4a-4320-b5d8-a2bb72bd8c03": "Apparel",
    "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0": "Electronics",
    "fea01756-1ba1-4b38-841f-c6a2b86bb2a6": "Grocery",
    "fcaaec3d-21d4-461d-9dbe-849c7c14c7de": "Health & Wellness",
    "c346f439-e972-4f0a-8115-f3baa63cc1d8": "Home Essentials",
    "adf36cbb-9243-4a60-96ac-f5998361ed91": "Office Supplies",
    "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec": "Personal Care",
    "7fb054a9-5457-4932-9c89-4701da3f1dcc": "Pet Supplies",
    "64c198d3-3bcc-4291-ab8d-7e12abf24b2f": "Snacks & Beverages",
    "78e2ee6c-ee94-4bdc-ad4a-405ff2332e65": "Toys & Games",
}
CATEGORY_ID = {v: k for k, v in CATEGORY_MAP.items()}  # name → id

SKU_PREFIX = {
    "Apparel":            "APP",
    "Electronics":        "ELEC",
    "Grocery":            "GRO",
    "Health & Wellness":  "HW",
    "Home Essentials":    "HOME",
    "Office Supplies":    "OFF",
    "Personal Care":      "PC",
    "Pet Supplies":       "PET",
    "Snacks & Beverages": "SNK",
    "Toys & Games":       "TOY",
}

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")


# ── Helpers ───────────────────────────────────────────────────────────────────

def sql_str(s: str) -> str:
    """Escape a string for SQL (single-quote safe)."""
    return "'" + s.replace("'", "''") + "'"


def get_image_products(category_folder: str) -> list[str]:
    path = os.path.join(IMAGE_BASE, category_folder)
    if not os.path.isdir(path):
        return []
    return sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))


def make_sku(prefix: str, product_name: str, index: int) -> str:
    words = re.sub(r'[^a-zA-Z0-9 ]', '', product_name).split()
    key_words = [w for w in words if len(w) >= 3][:2]
    mid = '-'.join(w[:4].upper() for w in key_words) if key_words else 'PROD'
    return f"{prefix}-{mid}-{index:03d}"


def make_description(product_name: str, category: str) -> str:
    name = re.sub(r'\s+\S{1,3}$', '', product_name.strip())
    templates = {
        "Apparel":            f"Quality {name.split()[0] if name else 'clothing'} apparel item",
        "Electronics":        f"Electronic device: {name[:60]}",
        "Grocery":            f"Grocery item: {name[:60]}",
        "Health & Wellness":  f"Health supplement: {name[:60]}",
        "Home Essentials":    f"Home essential: {name[:60]}",
        "Office Supplies":    f"Office supply: {name[:60]}",
        "Personal Care":      f"Personal care product: {name[:60]}",
        "Pet Supplies":       f"Pet supply: {name[:60]}",
        "Snacks & Beverages": f"Snack or beverage: {name[:60]}",
        "Toys & Games":       f"Toy or game: {name[:60]}",
    }
    return templates.get(category, name[:80])


# ── Load CSV ──────────────────────────────────────────────────────────────────

with open(PRODUCT_CSV, encoding='utf-8') as f:
    rows = list(csv.DictReader(f))

# Track all product names currently in the dataset (per category)
from collections import defaultdict
dataset_names_by_cat: dict[str, set] = defaultdict(set)
for row in rows:
    cat = CATEGORY_MAP.get(row['category_id'], '')
    dataset_names_by_cat[cat].add(row['product_name'])

max_product_number = max(int(r['product_number']) for r in rows)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. UPDATE SCRIPT  – every row in the dataset, set name/sku/description
# ═══════════════════════════════════════════════════════════════════════════════

update_lines = [
    "-- ============================================================",
    "-- UPDATE products: refresh product_name, sku, description",
    "-- Generated: " + NOW,
    "-- ============================================================",
    "",
]

for row in rows:
    cat = CATEGORY_MAP.get(row['category_id'], 'Unknown')
    update_lines.append(
        f"-- [{cat}] #{row['product_number']} {row['product_name'][:60]}"
    )
    update_lines.append(
        f"UPDATE products"
    )
    update_lines.append(
        f"SET   product_name = {sql_str(row['product_name'])},"
    )
    update_lines.append(
        f"      sku         = {sql_str(row['sku'])},"
    )
    update_lines.append(
        f"      description = {sql_str(row['description'])},"
    )
    update_lines.append(
        f"      updated_at  = '{NOW}'"
    )
    update_lines.append(
        f"WHERE product_id  = '{row['product_id']}';"
    )
    update_lines.append("")

update_lines.append(f"-- Total: {len(rows)} rows updated")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INSERT SCRIPT  – image products not present in the dataset
# ═══════════════════════════════════════════════════════════════════════════════

insert_lines = [
    "-- ============================================================",
    "-- INSERT products: image-folder products not in dataset",
    "-- Generated: " + NOW,
    "-- ============================================================",
    "",
]

new_rows = []
seq = max_product_number + 1   # continue product_number sequence

for cat_id, category in CATEGORY_MAP.items():
    image_products = get_image_products(category)
    in_dataset     = dataset_names_by_cat.get(category, set())
    prefix         = SKU_PREFIX[category]

    missing = [p for p in image_products if p not in in_dataset]

    if missing:
        insert_lines.append(f"-- ── {category} ({len(missing)} new products) ──────────────────────────")

    for i, product_name in enumerate(missing, 1):
        new_id  = str(uuid.uuid4())
        sku     = make_sku(prefix, product_name, i + len(in_dataset))
        desc    = make_description(product_name, category)

        insert_lines.append(f"-- [{category}] {product_name[:70]}")
        insert_lines.append("INSERT INTO products (")
        insert_lines.append("    product_id, product_number, product_name, sku, description,")
        insert_lines.append("    category_id, stock_quantity, is_active, currency_code,")
        insert_lines.append("    created_at, updated_at, is_synthetic")
        insert_lines.append(") VALUES (")
        insert_lines.append(f"    '{new_id}',")
        insert_lines.append(f"    {seq},")
        insert_lines.append(f"    {sql_str(product_name)},")
        insert_lines.append(f"    '{sku}',")
        insert_lines.append(f"    {sql_str(desc)},")
        insert_lines.append(f"    '{cat_id}',")
        insert_lines.append( "    100,")
        insert_lines.append( "    TRUE,")
        insert_lines.append( "    'USD',")
        insert_lines.append(f"    '{NOW}',")
        insert_lines.append(f"    '{NOW}',")
        insert_lines.append( "    FALSE")
        insert_lines.append(");")
        insert_lines.append("")

        new_rows.append({'product_number': seq, 'product_name': product_name,
                         'category': category, 'sku': sku})
        seq += 1

total_inserts = seq - max_product_number - 1
insert_lines.append(f"-- Total: {total_inserts} new rows inserted")


# ── Write files ───────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(OUT_UPDATE), exist_ok=True)

with open(OUT_UPDATE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(update_lines))
print(f"Written: {OUT_UPDATE}  ({len(rows)} UPDATE statements)")

with open(OUT_INSERT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(insert_lines))
print(f"Written: {OUT_INSERT}  ({total_inserts} INSERT statements)")

if new_rows:
    print("\nNew products to insert:")
    for r in new_rows:
        print(f"  [{r['category']}] #{r['product_number']}  {r['product_name'][:70]}")
else:
    print("\nNo new products to insert (all image products are already in the dataset).")
