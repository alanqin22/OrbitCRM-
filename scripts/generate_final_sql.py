"""
Generate final SQL for replace_synthetic_products.sql
Uses actual folder names from disk.
"""
import os, re, uuid
from urllib.parse import quote
from datetime import datetime, timezone

IMAGE_BASE = r"D:\a\crm_agent\image"
SQL_OUT    = r"D:\a\crm_agent\sql\replace_synthetic_products.sql"
NOW        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
IMAGES_PER = 5

# 19 synthetic products: (syn_name, category, category_id, product_id, img_sort1_id, folder_hint)
# folder_hint = first ~15 chars of expected folder name to find the right one
PRODUCTS = [
    ("VoltEdge LED Desk Lamp",           "Electronics",      "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
     "bd5410ec-01ba-4307-b5d0-e6dc284577b6", "ae9ca7fa-fbe6-44ed-a582-ec94945793bd", "Honeywell Suntura"),
    ("PetNest Portable Pet Carrier",     "Pet Supplies",     "7fb054a9-5457-4932-9c89-4701da3f1dcc",
     "a480c2ec-027f-4931-955f-c8b6144bde05", "ef692941-a869-4122-8d30-2073f74e92e8", "Quaker Pet Group"),
    ("PaperNest Sticky Notes (12 Pack)", "Office Supplies",  "adf36cbb-9243-4a60-96ac-f5998361ed91",
     "0274bc65-9623-4170-9b66-a0aa858faf74", "e125b5c5-a6ea-40a3-be0e-5c4d92c49a44", "Sticky Notes 3x3"),
    ("Zentro Pantry Tomato Ketchup 500ml","Grocery",         "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec",
     "7297ec71-c4d1-4d10-b07f-62e16d8b84ea", "6f21bbea-bc32-4eb9-b9ab-769ca1e28e49", "Heinz Tomato Ketch"),
    ("WonderBox Color Match Card Game",  "Toys & Games",     "fea01756-1ba1-4b38-841f-c6a2b86bb2a6",
     "d6ba63de-5220-4fb7-9d9a-fbc7ea949f86", "d5888fcd-033b-44c3-80b3-9a407fbadd76", "Jax Sequence"),
    ("PlayForge Stuffed Teddy Bear",     "Toys & Games",     "fea01756-1ba1-4b38-841f-c6a2b86bb2a6",
     "3ef560b7-1001-489d-bd11-066af5e1e927", "19cf0776-a13d-40a1-8cd8-eb15b33e9b8d", "HollyHOME Teddy"),
    ("Solvante FreshMint Toothpaste 100ml","Personal Care",  "fcaaec3d-21d4-461d-9dbe-849c7c14c7de",
     "2b5fed52-d880-4c06-ba36-987532d81954", "96cd9d3c-5b73-4133-affd-affd18ecec84", "Hello Naturally"),
    ("PureGlow Soft Toothbrushes (2 Pack)","Personal Care",  "fcaaec3d-21d4-461d-9dbe-849c7c14c7de",
     "14c1d9ae-48d2-464a-aeb2-40728a9950c7", "bb149ce3-5916-4c20-8c3c-c4624423f776", "Oral B Pulsar"),
    ("PawHaven Pet Shampoo 500ml",       "Pet Supplies",     "7fb054a9-5457-4932-9c89-4701da3f1dcc",
     "a3be0660-961b-475b-840f-5cdc02314d55", "86f60855-dab2-4f91-9a48-d1267e4c961a", "Burt's Bees for"),
    ("QuietCool Desk Fan USB",           "Home Essentials",  "c346f439-e972-4f0a-8115-f3baa63cc1d8",
     "19df8f35-936c-4719-afad-3ad02e3fd2b9", "4b73821d-8412-41ec-a94b-20f55a544fb0", "6 Inch Desk USB"),
    ("FreshVale Whole Milk 1L",          "Grocery",          "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec",
     "42e5196b-c323-4947-9781-26147c5e8995", "8e049194-d250-4c65-a952-0772cb7c7825", "Whole Milk Powder"),
    ("DeskFlow Whiteboard Markers (5 Pack)","Office Supplies","adf36cbb-9243-4a60-96ac-f5998361ed91",
     "5b2ff158-be1c-40a4-badb-bb37d3da0246", "37d366de-67e2-4a9a-8e9a-6dc9b3ebc857", "25Pcs Black Magnet"),
    ("Solvante Non-Slip Yoga Mat",       "Health & Wellness","78e2ee6c-ee94-4bdc-ad4a-405ff2332e65",
     "519fe978-7b9e-4475-9aec-4c8b74b2a7fd", "44b66c89-04df-4d9f-87c6-a5c7aa6d673a", "Squat Mat"),
    ("Vitalis Vitamin D3 Softgels (100 Pack)","Health & Wellness","78e2ee6c-ee94-4bdc-ad4a-405ff2332e65",
     "1465249d-24ba-47d3-8611-f2e9b58b967b", "5deaf9ab-9bf8-4299-be34-ced575689ad1", "Vitamin D3 K2"),
    ("UltraSharp 27\" 4K Monitor",       "Electronics",      "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
     "f67879b2-7169-462b-a0b8-f35efdbbd6bb", "38c17772-31de-42f7-963c-ef0a80b19809", "Dell 24 Monitor"),
    ("CloudSync Backup Drive 4TB",       "Electronics",      "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
     "cdece7fe-a811-4f50-82ec-72fbf70c2455", "645bc54f-1543-43c5-a58e-2c0e39d64f3a", "Western Digital 5T"),
    ("CablePro USB-C Hub 10-Port",       "Electronics",      "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
     "a7859971-8230-4e14-a362-a5fcd6ed44b3", "eb919a28-9c95-4e22-b118-1da9e34444b9", "Powered USB 3.2"),
    ("QuickPrint Laser Toner Black",     "Office Supplies",  "adf36cbb-9243-4a60-96ac-f5998361ed91",
     "82285d6b-4b1d-4f2a-944a-352183b98b1e", "b232e73d-6ba7-4f5c-aa22-abedd1166743", "(New Chip) TN760"),
    ("LabelMax Pro Label Maker",         "Office Supplies",  "adf36cbb-9243-4a60-96ac-f5998361ed91",
     "c738e598-73e0-4cf9-baf5-daf1c65c3279", "550ba9a5-10fc-4f5e-b5f7-9249feffb17d", "DYMO LabelManager"),
]


def find_folder(category, hint):
    """Find exact folder name by hint (prefix match)."""
    cat_dir = os.path.join(IMAGE_BASE, category)
    if not os.path.isdir(cat_dir):
        return None
    hint_lower = hint.lower()
    for d in os.listdir(cat_dir):
        if os.path.isdir(os.path.join(cat_dir, d)) and d.lower().startswith(hint_lower):
            return d
    # Try partial match
    for d in os.listdir(cat_dir):
        if os.path.isdir(os.path.join(cat_dir, d)) and hint_lower[:10] in d.lower():
            return d
    return None


def count_images(folder):
    return sum(1 for f in os.listdir(folder) if f.lower().endswith('.jpg'))


def esc(s):
    return s.replace("'", "''")


def generate_sku(category, title):
    prefixes = {
        "Electronics": "ELEC", "Pet Supplies": "PET",
        "Office Supplies": "OFF", "Grocery": "GRO",
        "Toys & Games": "TOY", "Personal Care": "PER",
        "Home Essentials": "HOM", "Health & Wellness": "HLT",
        "Snacks & Beverages": "SNK", "Apparel": "APP",
    }
    prefix = prefixes.get(category, "PRD")
    words = re.sub(r'[^a-zA-Z0-9 ]', '', title).split()
    w1 = words[0][:4].upper() if words else "ITEM"
    w2 = words[1][:4].upper() if len(words) > 1 else ""
    return f"{prefix}-{w1}-{w2}-NEW".rstrip('-')


def url_encode_path(category, product_name):
    return f"image/{quote(category, safe='')}/{quote(product_name, safe='')}"


def main():
    print("Resolving folder names...")
    resolved = []
    missing  = []

    for (syn_name, category, category_id, product_id, img_sort1_id, hint) in PRODUCTS:
        folder_name = find_folder(category, hint)
        if folder_name:
            folder_path = os.path.join(IMAGE_BASE, category, folder_name)
            n_imgs = count_images(folder_path)
            print(f"  [OK] {syn_name[:35]:<35} -> {folder_name[:45]} ({n_imgs} imgs)")
            resolved.append({
                'synthetic_name': syn_name,
                'real_name': folder_name,
                'category': category,
                'category_id': category_id,
                'product_id': product_id,
                'img_sort1_id': img_sort1_id,
                'n_imgs': n_imgs,
            })
        else:
            print(f"  [MISSING] {syn_name[:35]} (hint: {hint})")
            missing.append(syn_name)

    if missing:
        print(f"\nMissing: {missing}")
        print("Cannot generate complete SQL - please fix missing products first.")
        return

    # Build SQL
    lines = [
        "-- ============================================================",
        "-- Replace 19 synthetic products with real Amazon.ca products",
        f"-- Generated: {NOW}",
        "-- ============================================================",
        "",
        "-- ── 1. UPDATE products table ─────────────────────────────────",
        "",
    ]

    for r in resolved:
        real_name = r['real_name']
        pid       = r['product_id']
        sku       = generate_sku(r['category'], real_name)
        desc      = f"{r['category']} product: {real_name[:80]}"
        lines.append(f"-- [{r['category']}] {r['synthetic_name']} -> {real_name[:45]}")
        lines.append( "UPDATE public.products")
        lines.append(f"SET   product_name  = '{esc(real_name)}',")
        lines.append(f"      description   = '{esc(desc)}',")
        lines.append(f"      sku           = '{esc(sku)}',")
        lines.append( "      is_synthetic  = FALSE,")
        lines.append(f"      updated_at    = '{NOW}'")
        lines.append(f"WHERE product_id = '{pid}';")
        lines.append("")

    lines += [
        "-- ── 2. UPDATE / INSERT product_image rows ────────────────────",
        "",
    ]

    for r in resolved:
        real_name  = r['real_name']
        pid        = r['product_id']
        img_sort1  = r['img_sort1_id']
        url_base   = url_encode_path(r['category'], real_name)

        lines.append(f"-- [{r['category']}] {real_name[:50]}")
        lines.append( "UPDATE product_image")
        lines.append(f"SET   image_url  = '{url_base}/image_1.jpg',")
        lines.append(f"      alt_text   = '{esc(real_name)} - image 1',")
        lines.append(f"      created_at = '{NOW}'")
        lines.append(f"WHERE product_image_id = '{img_sort1}';")
        lines.append("")

        for sort in range(2, IMAGES_PER + 1):
            new_id = str(uuid.uuid4())
            lines.append(
                f"INSERT INTO product_image"
                f" (product_image_id, product_id, image_url, sort_order, alt_text, created_at)"
            )
            lines.append(
                f"VALUES ('{new_id}', '{pid}',"
                f" '{url_base}/image_{sort}.jpg', {sort},"
                f" '{esc(real_name)} - image {sort}', '{NOW}')"
            )
            lines.append("ON CONFLICT (product_id, sort_order)")
            lines.append(
                "DO UPDATE SET image_url = EXCLUDED.image_url,"
                " alt_text = EXCLUDED.alt_text;"
            )
            lines.append("")

    lines.append(f"-- Total: {len(resolved)} products replaced")
    sql_content = "\n".join(lines)

    os.makedirs(os.path.dirname(SQL_OUT), exist_ok=True)
    with open(SQL_OUT, 'w', encoding='utf-8') as f:
        f.write(sql_content)

    print(f"\nSQL written to: {SQL_OUT}")
    print(f"Total: {len(resolved)} product replacements")
    print(f"       {len(resolved) * IMAGES_PER} product_image rows (1 UPDATE + 4 INSERT each)")


if __name__ == "__main__":
    main()
