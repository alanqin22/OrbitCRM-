"""
Replace remaining synthetic products (PaperNest + products 12-19).
Run after replace_synthetic_products.py.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from bs4 import BeautifulSoup
import os, re, json, time, random, uuid, shutil
from urllib.parse import urljoin, quote
from datetime import datetime, timezone

IMAGE_BASE   = r"D:\a\crm_agent\image"
IMAGES_PER   = 5
DELAY_MIN    = 2.5
DELAY_MAX    = 5.0
NOW          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Only the remaining ones not yet downloaded
REMAINING = [
    (
        "PaperNest Sticky Notes (12 Pack)",
        "Office Supplies",
        "adf36cbb-9243-4a60-96ac-f5998361ed91",
        "0274bc65-9623-4170-9b66-a0aa858faf74",
        "e125b5c5-a6ea-40a3-be0e-5c4d92c49a44",
        "Post-it sticky notes 3x3 multi color",
    ),
    (
        "DeskFlow Whiteboard Markers (5 Pack)",
        "Office Supplies",
        "adf36cbb-9243-4a60-96ac-f5998361ed91",
        "5b2ff158-be1c-40a4-badb-bb37d3da0246",
        "37d366de-67e2-4a9a-8e9a-6dc9b3ebc857",
        "Expo dry erase markers chisel tip 5 pack",
    ),
    (
        "Solvante Non-Slip Yoga Mat",
        "Health & Wellness",
        "78e2ee6c-ee94-4bdc-ad4a-405ff2332e65",
        "519fe978-7b9e-4475-9aec-4c8b74b2a7fd",
        "44b66c89-04df-4d9f-87c6-a5c7aa6d673a",
        "Gaiam yoga mat non-slip exercise fitness",
    ),
    (
        "Vitalis Vitamin D3 Softgels (100 Pack)",
        "Health & Wellness",
        "78e2ee6c-ee94-4bdc-ad4a-405ff2332e65",
        "1465249d-24ba-47d3-8611-f2e9b58b967b",
        "5deaf9ab-9bf8-4299-be34-ced575689ad1",
        "Webber Naturals Vitamin D3 1000 IU softgels",
    ),
    (
        "UltraSharp 27\" 4K Monitor",
        "Electronics",
        "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
        "f67879b2-7169-462b-a0b8-f35efdbbd6bb",
        "38c17772-31de-42f7-963c-ef0a80b19809",
        "LG 27 inch 4K UHD IPS monitor HDMI",
    ),
    (
        "CloudSync Backup Drive 4TB",
        "Electronics",
        "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
        "cdece7fe-a811-4f50-82ec-72fbf70c2455",
        "645bc54f-1543-43c5-a58e-2c0e39d64f3a",
        "Seagate 4TB portable external hard drive",
    ),
    (
        "CablePro USB-C Hub 10-Port",
        "Electronics",
        "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
        "a7859971-8230-4e14-a362-a5fcd6ed44b3",
        "eb919a28-9c95-4e22-b118-1da9e34444b9",
        "Anker USB-C hub 10 port docking station",
    ),
    (
        "QuickPrint Laser Toner Black",
        "Office Supplies",
        "adf36cbb-9243-4a60-96ac-f5998361ed91",
        "82285d6b-4b1d-4f2a-944a-352183b98b1e",
        "b232e73d-6ba7-4f5c-aa22-abedd1166743",
        "Brother TN760 high yield black toner cartridge",
    ),
    (
        "LabelMax Pro Label Maker",
        "Office Supplies",
        "adf36cbb-9243-4a60-96ac-f5998361ed91",
        "c738e598-73e0-4cf9-baf5-daf1c65c3279",
        "550ba9a5-10fc-4f5e-b5f7-9249feffb17d",
        "DYMO LabelManager 160 label maker",
    ),
]

# Products already completed from first run
COMPLETED = [
    {
        'synthetic_name': 'VoltEdge LED Desk Lamp',
        'real_name': 'Honeywell Sunturalux HWT-H01 LED Desk Lamp',
        'category': 'Electronics',
        'category_id': 'c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0',
        'product_id': 'bd5410ec-01ba-4307-b5d0-e6dc284577b6',
        'img_sort1_id': 'ae9ca7fa-fbe6-44ed-a582-ec94945793bd',
    },
    {
        'synthetic_name': 'PetNest Portable Pet Carrier',
        'real_name': 'Quaker Pet Group SPT11721 Sherpa PetDelta Carrier',
        'category': 'Pet Supplies',
        'category_id': '7fb054a9-5457-4932-9c89-4701da3f1dcc',
        'product_id': 'a480c2ec-027f-4931-955f-c8b6144bde05',
        'img_sort1_id': 'ef692941-a869-4122-8d30-2073f74e92e8',
    },
    {
        'synthetic_name': 'Zentro Pantry Tomato Ketchup 500ml',
        'real_name': 'Heinz Tomato Ketchup, 9L (Pack of 24)',
        'category': 'Grocery',
        'category_id': 'cdcbd1da-11a2-497a-bc1c-99ff2cd440ec',
        'product_id': '7297ec71-c4d1-4d10-b07f-62e16d8b84ea',
        'img_sort1_id': '6f21bbea-bc32-4eb9-b9ab-769ca1e28e49',
    },
    {
        'synthetic_name': 'WonderBox Color Match Card Game',
        'real_name': 'Jax Sequence - Original Sequence Game',
        'category': 'Toys & Games',
        'category_id': 'fea01756-1ba1-4b38-841f-c6a2b86bb2a6',
        'product_id': 'd6ba63de-5220-4fb7-9d9a-fbc7ea949f86',
        'img_sort1_id': 'd5888fcd-033b-44c3-80b3-9a407fbadd76',
    },
    {
        'synthetic_name': 'PlayForge Stuffed Teddy Bear',
        'real_name': 'HollyHOME Teddy Bear Plush Giant Stuffed',
        'category': 'Toys & Games',
        'category_id': 'fea01756-1ba1-4b38-841f-c6a2b86bb2a6',
        'product_id': '3ef560b7-1001-489d-bd11-066af5e1e927',
        'img_sort1_id': '19cf0776-a13d-40a1-8cd8-eb15b33e9b8d',
    },
    {
        'synthetic_name': 'Solvante FreshMint Toothpaste 100ml',
        'real_name': 'Hello Naturally Whitening Fluoride Toothpaste',
        'category': 'Personal Care',
        'category_id': 'fcaaec3d-21d4-461d-9dbe-849c7c14c7de',
        'product_id': '2b5fed52-d880-4c06-ba36-987532d81954',
        'img_sort1_id': '96cd9d3c-5b73-4133-affd-affd18ecec84',
    },
    {
        'synthetic_name': 'PureGlow Soft Toothbrushes (2 Pack)',
        'real_name': 'Oral B Pulsar Pro-Health Battery Toothbrush',
        'category': 'Personal Care',
        'category_id': 'fcaaec3d-21d4-461d-9dbe-849c7c14c7de',
        'product_id': '14c1d9ae-48d2-464a-aeb2-40728a9950c7',
        'img_sort1_id': 'bb149ce3-5916-4c20-8c3c-c4624423f776',
    },
    {
        'synthetic_name': "PawHaven Pet Shampoo 500ml",
        'real_name': "Burt's Bees for Dogs Natural Hypoallergenic",
        'category': 'Pet Supplies',
        'category_id': '7fb054a9-5457-4932-9c89-4701da3f1dcc',
        'product_id': 'a3be0660-961b-475b-840f-5cdc02314d55',
        'img_sort1_id': '86f60855-dab2-4f91-9a48-d1267e4c961a',
    },
    {
        'synthetic_name': 'QuietCool Desk Fan USB',
        'real_name': '6 Inch Desk USB Fan with 4 Strong Wind',
        'category': 'Home Essentials',
        'category_id': 'c346f439-e972-4f0a-8115-f3baa63cc1d8',
        'product_id': '19df8f35-936c-4719-afad-3ad02e3fd2b9',
        'img_sort1_id': '4b73821d-8412-41ec-a94b-20f55a544fb0',
    },
    {
        'synthetic_name': 'FreshVale Whole Milk 1L',
        'real_name': 'Whole Milk Powder, full cream, 1 lbbag',
        'category': 'Grocery',
        'category_id': 'cdcbd1da-11a2-497a-bc1c-99ff2cd440ec',
        'product_id': '42e5196b-c323-4947-9781-26147c5e8995',
        'img_sort1_id': '8e049194-d250-4c65-a952-0772cb7c7825',
    },
]


def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    })
    return s


def sleep(lo=None, hi=None):
    time.sleep(random.uniform(lo or DELAY_MIN, hi or DELAY_MAX))


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:50].rstrip(' ,.;-')


def fetch(session, url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 503:
                print(f"    503 waiting 15s (attempt {attempt+1})")
                time.sleep(15)
        except Exception as e:
            print(f"    Request error: {e}")
        time.sleep(5)
    return None


def search_amazon(session, query):
    encoded = query.replace(' ', '+')
    url = f"https://www.amazon.ca/s?k={encoded}"
    print(f"  Searching: {query}")
    sleep()
    html = fetch(session, url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'lxml')
    results = []
    for card in soup.select('[data-component-type="s-search-result"]'):
        asin = card.get('data-asin', '')
        if not asin:
            continue
        h2_link = card.select_one('h2 a')
        title_tag = card.select_one('h2 a span') or card.select_one('h2 span')
        if h2_link and h2_link.get('aria-label'):
            title = h2_link['aria-label'].strip()
        elif title_tag:
            title = title_tag.get_text(strip=True)
        else:
            continue
        link_tag = card.select_one('h2 a.a-link-normal') or card.select_one('a[href*="/dp/"]')
        href = link_tag['href'] if link_tag and link_tag.get('href') else f'/dp/{asin}'
        product_url = urljoin("https://www.amazon.ca", href.split('?')[0])
        if len(title) >= 15:
            results.append({'title': title, 'url': product_url})
    return results


def get_product_images(session, product_url):
    print(f"  Fetching: {product_url}")
    sleep()
    html = fetch(session, product_url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'lxml')
    image_urls = []
    for script in soup.find_all('script'):
        text = script.string or ''
        if "'colorImages'" in text or '"colorImages"' in text or 'ImageBlockATF' in text:
            found = re.findall(r'"hiRes"\s*:\s*"(https://[^"]+)"', text)
            if found:
                image_urls.extend(found)
            if not image_urls:
                found = re.findall(r'"large"\s*:\s*"(https://[^"]+)"', text)
                image_urls.extend(found)
            if image_urls:
                break
    if not image_urls:
        for img in soup.select('img[data-a-dynamic-image]'):
            data = img.get('data-a-dynamic-image', '{}')
            try:
                image_urls.extend(list(json.loads(data).keys()))
            except Exception:
                pass
    if not image_urls:
        main = soup.select_one('#landingImage, #imgBlkFront')
        if main:
            src = main.get('data-old-hires') or main.get('src', '')
            if src:
                image_urls.append(src)
        for thumb in soup.select('#altImages img'):
            src = thumb.get('src', '')
            src = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', src)
            if src.startswith('https://') and 'sprite' not in src:
                image_urls.append(src)
    seen, clean = set(), []
    for u in image_urls:
        u = u.strip()
        if u and u not in seen and 'sprite' not in u and u.startswith('http'):
            seen.add(u)
            clean.append(u)
    return clean[:IMAGES_PER]


def download_image(session, url, dest_path):
    try:
        r = session.get(url, timeout=20, stream=True)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(dest_path, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"    [img error] {e}")
    return False


def process_product(session, syn_name, category, category_id, product_id, img_sort1_id, query):
    print(f"\n{'='*60}")
    print(f"  Replacing: {syn_name}")
    print(f"  Query:     {query}")

    candidates = search_amazon(session, query)
    if not candidates:
        print("  No results, skipping.")
        return None

    prod = next((c for c in candidates if len(c['title']) >= 20), candidates[0])
    real_name = sanitize(prod['title'])
    print(f"  Selected:  {real_name}")

    image_urls = get_product_images(session, prod['url'])
    print(f"  Found {len(image_urls)} image(s)")
    if not image_urls:
        print("  No images, skipping.")
        return None

    folder = os.path.join(IMAGE_BASE, category, real_name)
    os.makedirs(folder, exist_ok=True)

    downloaded = 0
    for img_url in image_urls:
        if downloaded >= IMAGES_PER:
            break
        dest = os.path.join(folder, f"image_{downloaded+1}.jpg")
        if download_image(session, img_url, dest):
            downloaded += 1
            print(f"    Downloaded {downloaded}/{IMAGES_PER}")

    if downloaded < 3:
        print(f"  Only {downloaded} images - removing folder.")
        shutil.rmtree(folder, ignore_errors=True)
        return None

    # Pad to 5 images
    img1 = os.path.join(folder, 'image_1.jpg')
    for i in range(downloaded + 1, IMAGES_PER + 1):
        dest = os.path.join(folder, f'image_{i}.jpg')
        if not os.path.exists(dest) and os.path.exists(img1):
            shutil.copy2(img1, dest)

    print(f"  + Saved {min(downloaded, IMAGES_PER)} images to: {folder}")
    return {
        'synthetic_name': syn_name,
        'real_name': real_name,
        'category': category,
        'category_id': category_id,
        'product_id': product_id,
        'img_sort1_id': img_sort1_id,
    }


def esc(s):
    return s.replace("'", "''")


def url_encode_path(category, product_name):
    return f"image/{quote(category, safe='')}/{quote(product_name, safe='')}"


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


def build_sql(all_results):
    lines = [
        "-- ============================================================",
        "-- Replace 19 synthetic products with real Amazon.ca products",
        f"-- Generated: {NOW}",
        "-- ============================================================",
        "",
        "-- ── 1. UPDATE products table ─────────────────────────────────",
        "",
    ]

    for r in all_results:
        real_name = r['real_name']
        pid       = r['product_id']
        sku       = generate_sku(r['category'], real_name)
        desc      = f"{r['category']} product: {real_name[:80]}"
        lines.append(f"-- [{r['category']}] {r['synthetic_name']} -> {real_name[:45]}")
        lines.append(f"UPDATE public.products")
        lines.append(f"SET   product_name  = '{esc(real_name)}',")
        lines.append(f"      description   = '{esc(desc)}',")
        lines.append(f"      sku           = '{esc(sku)}',")
        lines.append(f"      is_synthetic  = FALSE,")
        lines.append(f"      updated_at    = '{NOW}'")
        lines.append(f"WHERE product_id = '{pid}';")
        lines.append("")

    lines += [
        "-- ── 2. UPDATE / INSERT product_image rows ────────────────────",
        "",
    ]

    for r in all_results:
        real_name  = r['real_name']
        pid        = r['product_id']
        img_sort1  = r['img_sort1_id']
        url_base   = url_encode_path(r['category'], real_name)

        lines.append(f"-- [{r['category']}] {real_name[:50]}")
        lines.append(f"UPDATE product_image")
        lines.append(f"SET   image_url  = '{url_base}/image_1.jpg',")
        lines.append(f"      alt_text   = '{esc(real_name)} - image 1',")
        lines.append(f"      created_at = '{NOW}'")
        lines.append(f"WHERE product_image_id = '{img_sort1}';")
        lines.append("")

        for sort in range(2, IMAGES_PER + 1):
            new_id = str(uuid.uuid4())
            lines.append(
                f"INSERT INTO product_image (product_image_id, product_id, image_url, sort_order, alt_text, created_at)"
            )
            lines.append(
                f"VALUES ('{new_id}', '{pid}', '{url_base}/image_{sort}.jpg', {sort},"
                f" '{esc(real_name)} - image {sort}', '{NOW}')"
            )
            lines.append(
                f"ON CONFLICT (product_id, sort_order)"
            )
            lines.append(
                f"DO UPDATE SET image_url = EXCLUDED.image_url, alt_text = EXCLUDED.alt_text;"
            )
            lines.append("")

    lines.append(f"-- Total: {len(all_results)} products replaced")
    return "\n".join(lines)


def verify_completed_folders():
    """Verify completed products actually have image folders and fix real_name if needed."""
    verified = []
    for r in COMPLETED:
        folder = os.path.join(IMAGE_BASE, r['category'], r['real_name'])
        if os.path.isdir(folder):
            imgs = [f for f in os.listdir(folder) if f.lower().endswith('.jpg')]
            print(f"  [OK] {r['real_name'][:50]} ({len(imgs)} imgs)")
            verified.append(r)
        else:
            # Try to find a close match
            cat_dir = os.path.join(IMAGE_BASE, r['category'])
            if os.path.isdir(cat_dir):
                for d in os.listdir(cat_dir):
                    key = r['real_name'][:20].lower()
                    if key in d.lower():
                        imgs = [f for f in os.listdir(os.path.join(cat_dir, d))
                                if f.lower().endswith('.jpg')]
                        if imgs:
                            print(f"  [FOUND] {d[:50]} ({len(imgs)} imgs)")
                            r2 = dict(r)
                            r2['real_name'] = d
                            verified.append(r2)
                            break
                else:
                    print(f"  [MISSING] {r['real_name'][:50]}")
    return verified


def main():
    print("Verifying already-completed products...")
    completed_verified = verify_completed_folders()

    session = make_session()
    print("\nWarming up session...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        sleep(2, 4)
    except Exception as e:
        print(f"  Warning: {e}")

    new_results = []
    failed = []

    for (syn_name, category, category_id, product_id, img_sort1_id, query) in REMAINING:
        result = process_product(
            session, syn_name, category, category_id,
            product_id, img_sort1_id, query
        )
        if result:
            new_results.append(result)
        else:
            failed.append(syn_name)
        session.headers['User-Agent'] = random.choice(USER_AGENTS)
        sleep(4, 8)

    all_results = completed_verified + new_results
    print(f"\n{'='*60}")
    print(f"  Total results: {len(all_results)}/19")
    if failed:
        print(f"  Failed: {failed}")

    if all_results:
        sql = build_sql(all_results)
        sql_path = r"D:\a\crm_agent\sql\replace_synthetic_products.sql"
        os.makedirs(os.path.dirname(sql_path), exist_ok=True)
        with open(sql_path, 'w', encoding='utf-8') as f:
            f.write(sql)
        print(f"\nSQL written to: {sql_path}")

    print("\nSummary:")
    for r in all_results:
        print(f"  [OK] {r['synthetic_name'][:35]:<35} -> {r['real_name'][:40]}")
    for f in failed:
        print(f"  [FAIL] {f}")


if __name__ == "__main__":
    main()
