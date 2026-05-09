"""
Generate two SQL scripts for the product_image table:

  sql/update_product_images.sql
      UPDATE product_image SET image_url, alt_text WHERE product_image_id = ...
      -- for every existing record whose product has a real image folder

  sql/insert_product_images.sql
      INSERT INTO product_image ...
      (a) sort_order 2-5 for all existing products that have image folders
      (b) sort_order 1-5 for the 6 brand-new products from insert_products.sql
"""

import csv, os, re, uuid
from urllib.parse import quote
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
PRODUCT_CSV       = r"D:\a\crm_agent\product dateset.csv"
PRODUCT_IMAGE_CSV = r"D:\a\crm_agent\product_image_dataset.csv"
INSERT_PRODUCTS   = r"D:\a\crm_agent\sql\insert_products.sql"
IMAGE_BASE        = r"D:\a\crm_agent\image"
OUT_UPDATE        = r"D:\a\crm_agent\sql\update_product_images.sql"
OUT_INSERT        = r"D:\a\crm_agent\sql\insert_product_images.sql"

# Relative path prefix — same root as web pages so the path resolves on any host.
# Pattern: image/{category}/{product_name}/image_N.jpg
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

# ── Helpers ───────────────────────────────────────────────────────────────────

def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def image_url(category: str, product_name: str, filename: str) -> str:
    """Build a fully-qualified, URL-encoded image URL."""
    return (
        BASE_URL
        + "/" + quote(category,    safe="")
        + "/" + quote(product_name, safe="")
        + "/" + quote(filename,     safe="")
    )


def get_images(category: str, product_name: str) -> list[str]:
    """Return sorted list of image filenames for a product folder."""
    folder = os.path.join(IMAGE_BASE, category, product_name)
    if not os.path.isdir(folder):
        return []
    return sorted(
        f for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )


def alt_text(product_name: str, sort_order: int) -> str:
    short = product_name[:80].rstrip()
    return f"{short} - image {sort_order}"


# ── Load data ─────────────────────────────────────────────────────────────────

with open(PRODUCT_CSV, encoding="utf-8") as f:
    products = list(csv.DictReader(f))

with open(PRODUCT_IMAGE_CSV, encoding="utf-8") as f:
    img_records = list(csv.DictReader(f))

# product_id → product row
pid_to_prod = {r["product_id"]: r for r in products}

# product_id → existing product_image row  (sort_order=1 record)
pid_to_imgrow = {r["product_id"]: r for r in img_records}

# ── Parse new-product UUIDs from insert_products.sql ─────────────────────────
with open(INSERT_PRODUCTS, encoding="utf-8") as f:
    insert_sql = f.read()

new_products: list[dict] = []

# Split into per-INSERT blocks on "-- [Category]" comment lines
raw_blocks = re.split(r'\n(?=-- \[[^\]]+\] )', insert_sql)
for block in raw_blocks:
    # Header comment: -- [Category] name
    hdr = re.match(r'-- \[([^\]]+)\] (.+)', block)
    if not hdr:
        continue
    cat      = hdr.group(1).strip()
    # UUID is the first quoted UUID in the VALUES block
    uid_m    = re.search(r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'", block)
    # product_number is the integer on the line after the UUID
    pnum_m   = re.search(r"'[0-9a-f-]{36}',\s*\n\s*(\d+),", block)
    # product_name is the single-quoted string on the line after product_number
    pname_m  = re.search(r"^\s+(\d+),\s*\n\s*'([^']+)',", block, re.MULTILINE)
    if not (uid_m and pnum_m and pname_m):
        continue
    new_products.append({
        "product_id":     uid_m.group(1),
        "product_name":   pname_m.group(2).replace("''", "'"),
        "category":       cat,
        "product_number": int(pnum_m.group(1)),
    })

print(f"New products from insert_products.sql: {len(new_products)}")
for p in new_products:
    print(f"  [{p['category']}] {p['product_name'][:60]}")

# ── Identify which existing products have real image folders ──────────────────
existing_with_folder = []   # list of (img_row, prod_row, category, images)

for img_row in img_records:
    prod = pid_to_prod.get(img_row["product_id"])
    if not prod:
        continue
    cat = CATEGORY_MAP.get(prod["category_id"], "")
    imgs = get_images(cat, prod["product_name"])
    if imgs:
        existing_with_folder.append((img_row, prod, cat, imgs))

print(f"\nExisting products with image folder: {len(existing_with_folder)}")
print(f"Existing products without image folder (synthetic, no change): "
      f"{len(img_records) - len(existing_with_folder)}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. UPDATE SCRIPT
#    For each existing product_image record (sort_order=1) that has a real
#    image folder: update image_url and alt_text to the first real image.
# ═══════════════════════════════════════════════════════════════════════════════

upd_lines = [
    "-- ============================================================",
    "-- UPDATE product_image: replace placeholder URLs with real",
    "--   image paths for products that have image folders.",
    "-- Generated: " + NOW,
    f"-- Base URL: {BASE_URL}",
    "-- ============================================================",
    "",
]

for img_row, prod, cat, imgs in sorted(
    existing_with_folder,
    key=lambda x: (x[2], x[1]["product_name"])
):
    first_img  = imgs[0]
    url        = image_url(cat, prod["product_name"], first_img)
    alt        = alt_text(prod["product_name"], 1)

    upd_lines.append(f"-- [{cat}] {prod['product_name'][:65]}")
    upd_lines.append( "UPDATE product_image")
    upd_lines.append(f"SET   image_url = {sql_str(url)},")
    upd_lines.append(f"      alt_text  = {sql_str(alt)}")
    upd_lines.append(f"WHERE product_image_id = '{img_row['product_image_id']}';")
    upd_lines.append("")

upd_lines.append(f"-- Total: {len(existing_with_folder)} rows updated")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INSERT SCRIPT
#    (a) sort_order 2-5 for existing products with image folders
#    (b) sort_order 1-5 for the 6 new products from insert_products.sql
# ═══════════════════════════════════════════════════════════════════════════════

ins_lines = [
    "-- ============================================================",
    "-- INSERT product_image: additional images for existing products",
    "--   (sort_order 2-5) and all images for new products (1-5).",
    "-- Generated: " + NOW,
    f"-- Base URL: {BASE_URL}",
    "-- ============================================================",
    "",
]

total_inserts = 0

# ── (a) Additional images for existing products ───────────────────────────────
ins_lines.append("-- ── (A) sort_order 2-5 for existing products with image folders ──────────────")
ins_lines.append("")

for img_row, prod, cat, imgs in sorted(
    existing_with_folder,
    key=lambda x: (x[2], x[1]["product_name"])
):
    extra = imgs[1:]   # skip first image (covered by UPDATE)
    if not extra:
        continue

    ins_lines.append(f"-- [{cat}] {prod['product_name'][:65]}")
    for order, fname in enumerate(extra, start=2):
        url = image_url(cat, prod["product_name"], fname)
        alt = alt_text(prod["product_name"], order)
        new_id = str(uuid.uuid4())

        ins_lines.append("INSERT INTO product_image")
        ins_lines.append("    (product_image_id, product_id, image_url, sort_order, alt_text, created_at)")
        ins_lines.append("VALUES (")
        ins_lines.append(f"    '{new_id}',")
        ins_lines.append(f"    '{prod['product_id']}',")
        ins_lines.append(f"    {sql_str(url)},")
        ins_lines.append(f"    {order},")
        ins_lines.append(f"    {sql_str(alt)},")
        ins_lines.append(f"    '{NOW}'")
        ins_lines.append(")")
        ins_lines.append("ON CONFLICT (product_id, sort_order)")
        ins_lines.append(f"DO UPDATE SET image_url = EXCLUDED.image_url, alt_text = EXCLUDED.alt_text;")
        total_inserts += 1
    ins_lines.append("")

# ── (b) All images for new products from insert_products.sql ─────────────────
ins_lines.append("-- ── (B) sort_order 1-5 for new products (from insert_products.sql) ──────────")
ins_lines.append("")

for np in new_products:
    cat       = np["category"]
    prod_name = np["product_name"]
    prod_id   = np["product_id"]
    imgs      = get_images(cat, prod_name)

    if not imgs:
        ins_lines.append(f"-- WARNING: no images found for [{cat}] {prod_name[:60]}")
        ins_lines.append("")
        continue

    ins_lines.append(f"-- [{cat}] {prod_name[:65]}")
    for order, fname in enumerate(imgs, start=1):
        url    = image_url(cat, prod_name, fname)
        alt    = alt_text(prod_name, order)
        new_id = str(uuid.uuid4())

        ins_lines.append("INSERT INTO product_image")
        ins_lines.append("    (product_image_id, product_id, image_url, sort_order, alt_text, created_at)")
        ins_lines.append("VALUES (")
        ins_lines.append(f"    '{new_id}',")
        ins_lines.append(f"    '{prod_id}',")
        ins_lines.append(f"    {sql_str(url)},")
        ins_lines.append(f"    {order},")
        ins_lines.append(f"    {sql_str(alt)},")
        ins_lines.append(f"    '{NOW}'")
        ins_lines.append(")")
        ins_lines.append("ON CONFLICT (product_id, sort_order)")
        ins_lines.append(f"DO UPDATE SET image_url = EXCLUDED.image_url, alt_text = EXCLUDED.alt_text;")
        total_inserts += 1
    ins_lines.append("")

ins_lines.append(f"-- Total: {total_inserts} rows inserted")


# ── Write files ───────────────────────────────────────────────────────────────
with open(OUT_UPDATE, "w", encoding="utf-8") as f:
    f.write("\n".join(upd_lines))

with open(OUT_INSERT, "w", encoding="utf-8") as f:
    f.write("\n".join(ins_lines))

print(f"\nWritten: {OUT_UPDATE}  ({len(existing_with_folder)} UPDATE statements)")
print(f"Written: {OUT_INSERT}  ({total_inserts} INSERT statements)")
