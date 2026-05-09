"""
Generate sql/restore_synthetic_images.sql:
  Restore pexels placeholder URLs for the 19 synthetic products whose
  product_image rows got incorrectly overwritten with broken relative paths.
"""

import csv
from datetime import datetime, timezone

PRODUCT_CSV       = r"D:\a\crm_agent\product dateset.csv"
PRODUCT_IMAGE_CSV = r"D:\a\crm_agent\product_image_dataset2.csv"
OUT               = r"D:\a\crm_agent\sql\restore_synthetic_images.sql"

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

# SKUs of synthetic products (no real image folder)
SYNTHETIC_SKUS = {
    'PET-PNS-CAR', 'OFF-PNS-STK', 'OFF-DSK-WBM', 'PER-SVN-TTH', 'PER-PGL-TBR',
    'HOM-FAN-USBD', 'GRO-FVF-MLK', 'OFS-LBL-MPRO', 'OFS-TNR-LSRBK', 'GRO-ZEN-KET',
    'TOY-WBX-UNO', 'TOY-PFG-TED', 'HLT-VTL-VTD', 'HLT-SVN-YOG',
    'ELEC-VED-LMP', 'ELC-MON-27K4', 'ELC-DRV-BK4T', 'ELC-HUB-UC10', 'PET-PHV-SHP',
}

def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

with open(PRODUCT_CSV, encoding="utf-8") as f:
    prods = list(csv.DictReader(f))

with open(PRODUCT_IMAGE_CSV, encoding="utf-8") as f:
    img2 = list(csv.DictReader(f))

pid_to_prod = {r["product_id"]: r for r in prods}
synthetic_pids = {p["product_id"] for p in prods if p["sku"] in SYNTHETIC_SKUS}

lines = [
    "-- ============================================================",
    "-- RESTORE pexels placeholder image URLs for synthetic products",
    "--   (products with no real image folder — keep placeholder so",
    "--    the page shows something rather than a broken image).",
    "-- Generated: " + NOW,
    "-- ============================================================",
    "",
]

count = 0
for row in img2:
    if row["product_id"] not in synthetic_pids:
        continue
    prod = pid_to_prod.get(row["product_id"])
    pname = prod["product_name"] if prod else row["alt_text"]
    orig_url = row["image_url"]

    lines.append(f"-- [{pname[:65]}]")
    lines.append("UPDATE product_image")
    lines.append(f"SET   image_url = {sql_str(orig_url)}")
    lines.append(f"WHERE product_image_id = '{row['product_image_id']}';")
    lines.append("")
    count += 1

lines.append(f"-- Total: {count} rows restored to pexels placeholder URLs")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Written: {OUT}  ({count} rows)")
