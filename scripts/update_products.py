"""
Update product_name, sku, and description in 'product dateset.csv'
using the real product names from the image/ subfolder structure.
"""

import csv
import os
import re

# ── Category ID → folder name mapping ────────────────────────────────────────
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

# SKU prefix per category
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

IMAGE_BASE = r"D:\a\crm_agent\image"
PRODUCT_CSV = r"D:\a\crm_agent\product dateset.csv"


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_image_products(category_folder: str) -> list[str]:
    """Return sorted list of product folder names for a category."""
    path = os.path.join(IMAGE_BASE, category_folder)
    if not os.path.isdir(path):
        return []
    return sorted(
        d for d in os.listdir(path)
        if os.path.isdir(os.path.join(path, d))
    )


def make_sku(prefix: str, product_name: str, index: int) -> str:
    """Generate a SKU like APP-ABOVE-001 from product name."""
    # Take first meaningful word (skip small words)
    words = re.sub(r'[^a-zA-Z0-9 ]', '', product_name).split()
    key_words = [w for w in words if len(w) >= 3][:2]
    mid = '-'.join(w[:4].upper() for w in key_words) if key_words else 'PROD'
    return f"{prefix}-{mid}-{index:03d}"


def make_description(product_name: str, category: str) -> str:
    """Generate a short description from the product name."""
    # Clean up truncation artifacts (trailing partial words)
    name = re.sub(r'\s+\S{1,3}$', '', product_name.strip())
    # Category-specific short descriptions
    desc_map = {
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
    return desc_map.get(category, name[:80])


# ── Load CSV ──────────────────────────────────────────────────────────────────

with open(PRODUCT_CSV, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

print(f"Loaded {len(rows)} products from CSV")

# ── Build category → sorted product rows mapping ──────────────────────────────
# Sort within each category by product_number (numeric)
from collections import defaultdict
cat_rows: dict[str, list] = defaultdict(list)
for row in rows:
    cat_rows[row['category_id']].append(row)

for cat_id in cat_rows:
    cat_rows[cat_id].sort(key=lambda r: int(r['product_number']))

# ── Update each category ──────────────────────────────────────────────────────
total_updated = 0

for cat_id, category_name in CATEGORY_MAP.items():
    image_products = get_image_products(category_name)
    dataset_rows   = cat_rows.get(cat_id, [])
    prefix         = SKU_PREFIX[category_name]
    n_update       = min(len(image_products), len(dataset_rows))

    print(f"\n{category_name}: {len(dataset_rows)} in dataset, "
          f"{len(image_products)} images -> updating {n_update}")

    for i in range(n_update):
        row          = dataset_rows[i]
        product_name = image_products[i]  # folder name = real product name

        old_name = row['product_name']
        row['product_name'] = product_name
        row['sku']          = make_sku(prefix, product_name, i + 1)
        row['description']  = make_description(product_name, category_name)

        print(f"  [{i+1:2}] {old_name[:40]:40s} -> {product_name[:60]}")
        total_updated += 1

    # Rows beyond the image count keep their original values
    for i in range(n_update, len(dataset_rows)):
        print(f"  [{i+1:2}] (kept) {dataset_rows[i]['product_name'][:60]}")

# ── Write updated CSV ─────────────────────────────────────────────────────────
with open(PRODUCT_CSV, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)

print(f"\nDone. Updated {total_updated} products. CSV saved to '{PRODUCT_CSV}'")
