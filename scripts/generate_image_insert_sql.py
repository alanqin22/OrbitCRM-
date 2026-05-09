"""
Generate INSERT SQL for sort_orders 2-5 of the 7 Electronics products.
These rows don't exist in Supabase yet — only sort_order 1 is in the DB.
Uses image_N.jpg filenames (files confirmed uploaded to cPanel).
"""
import csv, uuid
from urllib.parse import quote

CSV_PATH = r"D:\a\crm_agent\product_image_dataset2.csv"
SQL_OUT  = r"D:\a\crm_agent\sql\insert_electronics_images.sql"
NOW      = "2026-03-27 12:30:00+00"

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


def enc(s):
    return quote(s, safe='')


def esc(s):
    return s.replace("'", "''")


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
        "-- INSERT sort_orders 2-5 for 7 Electronics products",
        "-- (sort_order 1 already exists in DB; 2-5 were never inserted)",
        f"-- Generated: {NOW}",
        "-- ============================================================",
        "-- Uses ON CONFLICT DO NOTHING so it is safe to re-run.",
        "",
    ]

    insert_count = 0
    for pid, folder_name in ELECTRONICS_PRODUCTS:
        pid_rows = by_pid.get(pid, {})
        lines.append(f"-- {folder_name}")
        for sort in range(2, 6):
            # Use the product_image_id from dataset2 so it matches local records
            row = pid_rows.get(sort)
            img_id = row['product_image_id'] if row else str(uuid.uuid4())
            url    = (f"image/{enc('Electronics')}/{enc(folder_name)}"
                      f"/image_{sort}.jpg")
            alt    = f"{esc(folder_name[:80])} - image {sort}"

            lines.append(
                "INSERT INTO product_image"
                " (product_image_id, product_id, image_url, sort_order, alt_text, created_at)"
            )
            lines.append(
                f"VALUES ('{img_id}', '{pid}',"
                f" '{url}', {sort},"
                f" '{alt}', '{NOW}')"
            )
            lines.append("ON CONFLICT (product_id, sort_order)")
            lines.append(
                f"DO UPDATE SET image_url = '{url}',"
                f" alt_text = '{alt}';"
            )
            lines.append("")
            insert_count += 1

    lines.append(f"-- Total: {insert_count} INSERT statements (7 products × 4 sort_orders)")

    sql = "\n".join(lines)
    with open(SQL_OUT, 'w', encoding='utf-8') as f:
        f.write(sql)

    print(f"SQL written to: {SQL_OUT}")
    print(f"  {insert_count} INSERT ... ON CONFLICT DO UPDATE statements")


if __name__ == "__main__":
    main()
