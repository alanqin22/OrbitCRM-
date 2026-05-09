"""
Fix product_image URLs:
1. Electronics products (7): sort_orders 2-5 still have Amazon CDN filenames.
   The local files were renamed to image_N.jpg and uploaded. UPDATE to image_N.jpg.
2. EcoWrite: sort_order 1 points to a non-existent local path. Restore pexels URL.
"""
import csv, uuid
from urllib.parse import quote

CSV_PATH = r"D:\a\crm_agent\product_image_dataset2.csv"
SQL_OUT  = r"D:\a\crm_agent\sql\fix_product_images.sql"
NOW      = "2026-03-27 12:30:00+00"

BASE_URL = "https://hemera.canspace.ca"

# 7 Electronics products that had Amazon filenames renamed to image_N.jpg
ELECTRONICS_PRODUCTS = [
    ("83d42df8-1702-4420-a75a-6cf115a9ddad",
     "Apple 2026 MacBook Neo 13-inch Laptop with Apple A18 Pro chip"),
    ("1918d621-c3d4-4477-9e81-a08a4f331bfe",
     "Brother DCP-L2640DW Business Monochrome Multifunction Laser Printer"),
    ("f67609ab-f273-4fb2-8210-8480dd54a6ed",
     "Lenovo ThinkPad T490 14'' FHD (1920 x 1080) IPS Business Laptop Computer"),
    ("9841ac0c-f665-47d6-b75c-76c0dcdce67f",
     "LG 24U411A-B 23.8  FHD (1920x1080)  IPS  120Hz"),
    ("775e330d-4aa2-4533-b809-f7fbcac4eae6",
     "Sony Alpha ZVE10 APSC Mirrorless Interchangeable Lens Camera"),
    ("603f184e-782b-430a-993f-9b6b95952685",
     "WD 2TB My Passport Portable External Hard Drive HDD"),
    ("e59f53fe-b2a2-4664-8212-8d4c45aa8ccc",
     "MSI Gaming RTX 5090 32G SUPRIM SOC Graphics Card"),
]

# EcoWrite - sort_order 1 broken local URL → restore working pexels URL
ECOWRITE = {
    "product_image_id": "23b04f4d-d708-4462-aab8-4fa8917f235e",
    "product_id":       "5660c3cb-1c79-4939-90c6-03d089a83626",
    "pexels_url": (
        "https://images.pexels.com/photos/272980/pexels-photo-272980.jpeg"
        "?auto=compress&cs=tinysrgb&w=800&h=800&fit=crop"
    ),
}


def enc(s):
    """URL-encode a path component (space → %20, etc.)"""
    return quote(s, safe='')


def image_url(category, folder, n):
    return f"image/{enc(category)}/{enc(folder)}/image_{n}.jpg"


def main():
    with open(CSV_PATH, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    by_pid = {}
    for r in rows:
        pid = r['product_id']
        so  = int(r['sort_order'])
        by_pid.setdefault(pid, {})[so] = r

    lines = [
        "-- ============================================================",
        "-- Fix broken product_image URLs",
        f"-- Generated: {NOW}",
        "-- ============================================================",
        "",
        "-- ── 1. Electronics: UPDATE sort_orders 2-5 from Amazon CDN filenames",
        "--       to image_N.jpg (files already uploaded to cPanel) ──────",
        "",
    ]

    update_count = 0
    for pid, folder_name in ELECTRONICS_PRODUCTS:
        pid_rows = by_pid.get(pid, {})
        lines.append(f"-- {folder_name[:60]}")
        for sort in range(2, 6):
            row = pid_rows.get(sort)
            if not row:
                lines.append(f"-- WARNING: sort_order {sort} not found in dataset for {pid[:8]}")
                continue
            img_id = row['product_image_id']
            url    = image_url("Electronics", folder_name, sort)
            alt    = f"{folder_name[:70]} - image {sort}"
            lines.append("UPDATE product_image")
            lines.append(f"SET   image_url = '{url}',")
            lines.append(f"      alt_text  = '{alt.replace(chr(39), chr(39)+chr(39))}'")
            lines.append(f"WHERE product_image_id = '{img_id}';")
            lines.append("")
            update_count += 1

    lines += [
        f"-- Electronics subtotal: {update_count} UPDATE statements",
        "",
        "-- ── 2. EcoWrite: restore sort_order 1 to working pexels URL ───",
        "",
    ]

    pexels = ECOWRITE['pexels_url']
    eco_id = ECOWRITE['product_image_id']
    lines.append("-- EcoWrite Recycled Notebook 3pk - sort_order 1")
    lines.append("UPDATE product_image")
    lines.append(f"SET   image_url = '{pexels}',")
    lines.append( "      alt_text  = 'EcoWrite Recycled Notebook 3pk - image 1'")
    lines.append(f"WHERE product_image_id = '{eco_id}';")
    lines.append("")
    lines.append(f"-- Total: {update_count + 1} UPDATE statements")

    sql = "\n".join(lines)
    with open(SQL_OUT, 'w', encoding='utf-8') as f:
        f.write(sql)

    print(f"SQL written to: {SQL_OUT}")
    print(f"  Electronics sort_orders 2-5: {update_count} UPDATEs")
    print(f"  EcoWrite sort_order 1:        1 UPDATE")
    print(f"  Total:                        {update_count + 1} UPDATEs")


if __name__ == "__main__":
    main()
