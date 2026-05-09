"""
Generate sql/update_product_images2.sql:
  UPDATE product_image SET image_url, alt_text
  WHERE product_image_id = ...
  for every row in product_image_dataset2.csv
"""

import csv, os
from urllib.parse import quote
from datetime import datetime, timezone

PRODUCT_CSV       = r"D:\a\crm_agent\product dateset.csv"
PRODUCT_IMAGE_CSV = r"D:\a\crm_agent\product_image_dataset2.csv"
INSERT_PRODUCTS   = r"D:\a\crm_agent\sql\insert_products.sql"
OUT_UPDATE        = r"D:\a\crm_agent\sql\update_product_images2.sql"

BASE_URL = "image"

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

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


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def image_url(category: str, product_name: str, sort_order: int) -> str:
    return (
        BASE_URL
        + "/" + quote(category,      safe="")
        + "/" + quote(product_name,  safe="")
        + "/image_" + str(sort_order) + ".jpg"
    )


def alt_text(product_name: str, sort_order: int) -> str:
    short = product_name[:80].rstrip()
    return f"{short} - image {sort_order}"


# ── Load data ─────────────────────────────────────────────────────────────────

import re

with open(PRODUCT_CSV, encoding="utf-8") as f:
    products = list(csv.DictReader(f))

with open(PRODUCT_IMAGE_CSV, encoding="utf-8") as f:
    img_records = list(csv.DictReader(f))

with open(INSERT_PRODUCTS, encoding="utf-8") as f:
    insert_sql = f.read()

pid_to_prod = {r["product_id"]: r for r in products}

# ── Add new products from insert_products.sql into the lookup map ─────────────
raw_blocks = re.split(r'\n(?=-- \[[^\]]+\] )', insert_sql)
for block in raw_blocks:
    hdr    = re.match(r'-- \[([^\]]+)\] (.+)', block)
    uid_m  = re.search(r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'", block)
    pname_m = re.search(r'^\s+(\d+),\s*\n\s*\'([^\']+)\',', block, re.MULTILINE)
    if not (hdr and uid_m and pname_m):
        continue
    pid = uid_m.group(1)
    if pid not in pid_to_prod:
        # Reverse-lookup category_id from category name
        cat_name = hdr.group(1).strip()
        cat_id = next((k for k, v in CATEGORY_MAP.items() if v == cat_name), "")
        pid_to_prod[pid] = {
            "product_id":   pid,
            "product_name": pname_m.group(2).replace("''", "'"),
            "category_id":  cat_id,
        }

# ── Generate UPDATE statements ────────────────────────────────────────────────

lines = [
    "-- ============================================================",
    "-- UPDATE product_image: replace pexels placeholder URLs with",
    "--   relative image paths for all rows in product_image_dataset2.",
    "-- Generated: " + NOW,
    f"-- Base URL: {BASE_URL}",
    f"-- Total rows: {len(img_records)}",
    "-- ============================================================",
    "",
]

skipped = 0
updated = 0

for row in img_records:
    prod = pid_to_prod.get(row["product_id"])
    if not prod:
        lines.append(f"-- WARNING: product_id {row['product_id']} not found in product dataset")
        skipped += 1
        continue

    cat = CATEGORY_MAP.get(prod["category_id"], "")
    if not cat:
        lines.append(f"-- WARNING: unknown category_id {prod['category_id']} for product {prod['product_name'][:50]}")
        skipped += 1
        continue

    order     = int(row["sort_order"])
    prod_name = prod["product_name"]
    url       = image_url(cat, prod_name, order)
    alt       = alt_text(prod_name, order)

    lines.append(f"-- [{cat}] {prod_name[:65]} (sort {order})")
    lines.append("UPDATE product_image")
    lines.append(f"SET   image_url = {sql_str(url)},")
    lines.append(f"      alt_text  = {sql_str(alt)}")
    lines.append(f"WHERE product_image_id = '{row['product_image_id']}';")
    lines.append("")
    updated += 1

lines.append(f"-- Total: {updated} rows updated, {skipped} skipped")

with open(OUT_UPDATE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Written: {OUT_UPDATE}")
print(f"  Updated: {updated}  Skipped: {skipped}")
