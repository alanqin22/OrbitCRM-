"""
Replace 19 synthetic products with real Amazon.ca products.
- Searches Amazon.ca for each synthetic product
- Downloads 5 images to image/[Category]/[Product Name]/
- Generates SQL to update products + product_image tables
"""

import requests
from bs4 import BeautifulSoup
import os, re, json, time, random, uuid, shutil
from urllib.parse import urljoin, quote
from datetime import datetime, timezone

# ── Constants ─────────────────────────────────────────────────────────────────
IMAGE_BASE   = r"D:\a\crm_agent\image"
SQL_OUT      = r"D:\a\crm_agent\sql\replace_synthetic_products.sql"
IMAGES_PER   = 5
DELAY_MIN    = 2.5
DELAY_MAX    = 5.0
NOW          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 19 Synthetic products to replace ─────────────────────────────────────────
# Format: (synthetic_name, category_folder, category_id, product_id,
#          img_sort1_id, search_query)
SYNTHETIC_PRODUCTS = [
    (
        "VoltEdge LED Desk Lamp",
        "Electronics",
        "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
        "bd5410ec-01ba-4307-b5d0-e6dc284577b6",
        "ae9ca7fa-fbe6-44ed-a582-ec94945793bd",
        "LED desk lamp dimmable USB",
    ),
    (
        "PetNest Portable Pet Carrier",
        "Pet Supplies",
        "7fb054a9-5457-4932-9c89-4701da3f1dcc",
        "a480c2ec-027f-4931-955f-c8b6144bde05",
        "ef692941-a869-4122-8d30-2073f74e92e8",
        "Sherpa Original Deluxe Airline pet carrier",
    ),
    (
        "PaperNest Sticky Notes (12 Pack)",
        "Office Supplies",
        "adf36cbb-9243-4a60-96ac-f5998361ed91",
        "0274bc65-9623-4170-9b66-a0aa858faf74",
        "e125b5c5-a6ea-40a3-be0e-5c4d92c49a44",
        "Post-it Super Sticky Notes 3x3 12 pads",
    ),
    (
        "Zentro Pantry Tomato Ketchup 500ml",
        "Grocery",
        "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec",
        "7297ec71-c4d1-4d10-b07f-62e16d8b84ea",
        "6f21bbea-bc32-4eb9-b9ab-769ca1e28e49",
        "Heinz tomato ketchup 500ml",
    ),
    (
        "WonderBox Color Match Card Game",
        "Toys & Games",
        "fea01756-1ba1-4b38-841f-c6a2b86bb2a6",
        "d6ba63de-5220-4fb7-9d9a-fbc7ea949f86",
        "d5888fcd-033b-44c3-80b3-9a407fbadd76",
        "Sequence card game board game family",
    ),
    (
        "PlayForge Stuffed Teddy Bear",
        "Toys & Games",
        "fea01756-1ba1-4b38-841f-c6a2b86bb2a6",
        "3ef560b7-1001-489d-bd11-066af5e1e927",
        "19cf0776-a13d-40a1-8cd8-eb15b33e9b8d",
        "stuffed teddy bear plush toy kids",
    ),
    (
        "Solvante FreshMint Toothpaste 100ml",
        "Personal Care",
        "fcaaec3d-21d4-461d-9dbe-849c7c14c7de",
        "2b5fed52-d880-4c06-ba36-987532d81954",
        "96cd9d3c-5b73-4133-affd-affd18ecec84",
        "Colgate Total toothpaste mint whitening",
    ),
    (
        "PureGlow Soft Toothbrushes (2 Pack)",
        "Personal Care",
        "fcaaec3d-21d4-461d-9dbe-849c7c14c7de",
        "14c1d9ae-48d2-464a-aeb2-40728a9950c7",
        "bb149ce3-5916-4c20-8c3c-c4624423f776",
        "Oral-B soft toothbrush 2 pack",
    ),
    (
        "PawHaven Pet Shampoo 500ml",
        "Pet Supplies",
        "7fb054a9-5457-4932-9c89-4701da3f1dcc",
        "a3be0660-961b-475b-840f-5cdc02314d55",
        "86f60855-dab2-4f91-9a48-d1267e4c961a",
        "Burt's Bees hypoallergenic pet shampoo 473ml",
    ),
    (
        "QuietCool Desk Fan USB",
        "Home Essentials",
        "c346f439-e972-4f0a-8115-f3baa63cc1d8",
        "19df8f35-936c-4719-afad-3ad02e3fd2b9",
        "4b73821d-8412-41ec-a94b-20f55a544fb0",
        "OPOLAR USB desk fan portable quiet 6 inch",
    ),
    (
        "FreshVale Whole Milk 1L",
        "Grocery",
        "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec",
        "42e5196b-c323-4947-9781-26147c5e8995",
        "8e049194-d250-4c65-a952-0772cb7c7825",
        "Natrel whole milk 1L homogenized",
    ),
    (
        "DeskFlow Whiteboard Markers (5 Pack)",
        "Office Supplies",
        "adf36cbb-9243-4a60-96ac-f5998361ed91",
        "5b2ff158-be1c-40a4-badb-bb37d3da0246",
        "37d366de-67e2-4a9a-8e9a-6dc9b3ebc857",
        "Expo low odour dry erase markers 5 pack",
    ),
    (
        "Solvante Non-Slip Yoga Mat",
        "Health & Wellness",
        "78e2ee6c-ee94-4bdc-ad4a-405ff2332e65",
        "519fe978-7b9e-4475-9aec-4c8b74b2a7fd",
        "44b66c89-04df-4d9f-87c6-a5c7aa6d673a",
        "Gaiam Premium non-slip yoga mat 6mm",
    ),
    (
        "Vitalis Vitamin D3 Softgels (100 Pack)",
        "Health & Wellness",
        "78e2ee6c-ee94-4bdc-ad4a-405ff2332e65",
        "1465249d-24ba-47d3-8611-f2e9b58b967b",
        "5deaf9ab-9bf8-4299-be34-ced575689ad1",
        "Webber Naturals Vitamin D3 1000 IU 100 softgels",
    ),
    (
        "UltraSharp 27\" 4K Monitor",
        "Electronics",
        "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0",
        "f67879b2-7169-462b-a0b8-f35efdbbd6bb",
        "38c17772-31de-42f7-963c-ef0a80b19809",
        "LG 27 inch 4K UHD IPS monitor",
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
        "Anker 10 port USB-C hub docking station",
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

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    })
    return s


def sleep(lo=None, hi=None):
    time.sleep(random.uniform(lo or DELAY_MIN, hi or DELAY_MAX))


def sanitize(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # Limit to 50 chars to avoid Windows MAX_PATH issues, then strip trailing punctuation
    return name[:50].rstrip(' ,.;-')


def fetch(session, url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 503:
                print(f"    503 – sleeping 15s (attempt {attempt+1})")
                time.sleep(15)
            else:
                print(f"    HTTP {r.status_code}")
        except Exception as e:
            print(f"    Request error: {e}")
        time.sleep(5)
    return None

# ── Amazon search ─────────────────────────────────────────────────────────────

def search_amazon(session, query, pages=3):
    """Return list of {title, url, asin} from Amazon.ca search."""
    encoded = query.replace(' ', '+')
    results = []
    for page in range(1, pages + 1):
        url = f"https://www.amazon.ca/s?k={encoded}&page={page}"
        print(f"  Searching: {url}")
        sleep()
        html = fetch(session, url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'lxml')
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
                results.append({'title': title, 'url': product_url, 'asin': asin})
        if results:
            break  # one good page is enough
    return results


def get_product_images(session, product_url):
    """Return up to IMAGES_PER high-res image URLs from a product page."""
    print(f"  Fetching product page: {product_url}")
    sleep()
    html = fetch(session, product_url)
    if not html:
        return []

    soup = BeautifulSoup(html, 'lxml')
    image_urls = []

    # Strategy 1: colorImages JSON blob
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

    # Strategy 2: data-a-dynamic-image
    if not image_urls:
        for img in soup.select('img[data-a-dynamic-image]'):
            data = img.get('data-a-dynamic-image', '{}')
            try:
                image_urls.extend(list(json.loads(data).keys()))
            except Exception:
                pass

    # Strategy 3: main + thumbnail images
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

    # Deduplicate
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

# ── SQL helpers ───────────────────────────────────────────────────────────────

def esc(s):
    """Escape single quotes for SQL."""
    return s.replace("'", "''")


def url_encode_path(category, product_name):
    """Build the image URL path with proper URL encoding."""
    cat_enc  = quote(category,      safe='')
    name_enc = quote(product_name,  safe='')
    return f"image/{cat_enc}/{name_enc}"


def generate_sku(category, title):
    """Generate a reasonable SKU from category + title words."""
    prefixes = {
        "Electronics":     "ELEC",
        "Pet Supplies":    "PET",
        "Office Supplies": "OFF",
        "Grocery":         "GRO",
        "Toys & Games":    "TOY",
        "Personal Care":   "PER",
        "Home Essentials": "HOM",
        "Health & Wellness": "HLT",
        "Snacks & Beverages": "SNK",
        "Apparel":         "APP",
    }
    prefix = prefixes.get(category, "PRD")
    words = re.sub(r'[^a-zA-Z0-9 ]', '', title).split()
    w1 = words[0][:4].upper() if len(words) > 0 else "ITEM"
    w2 = words[1][:4].upper() if len(words) > 1 else ""
    return f"{prefix}-{w1}-{w2}-NEW".rstrip('-')

# ── Main logic ────────────────────────────────────────────────────────────────

def process_product(session, synthetic_name, category, category_id,
                    product_id, img_sort1_id, search_query):
    print(f"\n{'='*65}")
    print(f"  Replacing: {synthetic_name}")
    print(f"  Category:  {category}")
    print(f"  Query:     {search_query}")
    print(f"{'='*65}")

    # 1. Search Amazon.ca
    candidates = search_amazon(session, search_query)
    if not candidates:
        print("  No results, skipping.")
        return None

    # Pick the first candidate with a reasonably long title
    prod = None
    for c in candidates:
        if len(c['title']) >= 20:
            prod = c
            break
    if not prod:
        prod = candidates[0]

    real_name   = sanitize(prod['title'])
    product_url = prod['url']
    print(f"  Selected:  {real_name[:70]}")

    # 2. Get image URLs from product page
    image_urls = get_product_images(session, product_url)
    print(f"  Found {len(image_urls)} image(s)")

    if not image_urls:
        print("  No images found, skipping.")
        return None

    # 3. Download images
    folder = os.path.join(IMAGE_BASE, category, real_name)
    os.makedirs(folder, exist_ok=True)

    downloaded = 0
    for i, img_url in enumerate(image_urls):
        if downloaded >= IMAGES_PER:
            break
        ext = '.jpg'
        m = re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', img_url, re.I)
        if m:
            ext = '.' + m.group(1).lower()
        dest = os.path.join(folder, f"image_{downloaded+1}{ext}")
        ok = download_image(session, img_url, dest)
        if ok:
            downloaded += 1
            print(f"    Downloaded {downloaded}/{IMAGES_PER}")

    if downloaded < 3:
        print(f"  Only {downloaded} images — removing folder.")
        shutil.rmtree(folder, ignore_errors=True)
        return None

    # Rename to .jpg if needed (ensure consistent extension)
    for fname in os.listdir(folder):
        fpath = os.path.join(folder, fname)
        if not fname.lower().endswith('.jpg') and os.path.isfile(fpath):
            base = os.path.splitext(fname)[0]
            new_path = os.path.join(folder, base + '.jpg')
            if not os.path.exists(new_path):
                os.rename(fpath, new_path)

    # Pad missing images with copies of image_1.jpg if fewer than 5
    img1 = os.path.join(folder, 'image_1.jpg')
    for i in range(downloaded + 1, IMAGES_PER + 1):
        dest = os.path.join(folder, f'image_{i}.jpg')
        if not os.path.exists(dest) and os.path.exists(img1):
            shutil.copy2(img1, dest)

    print(f"  + Saved {min(downloaded, IMAGES_PER)} images to: {folder}")

    return {
        'synthetic_name': synthetic_name,
        'real_name':       real_name,
        'category':        category,
        'category_id':     category_id,
        'product_id':      product_id,
        'img_sort1_id':    img_sort1_id,
        'downloaded':      downloaded,
    }


def build_sql(results):
    lines = [
        "-- ============================================================",
        "-- Replace 19 synthetic products with real Amazon.ca products",
        f"-- Generated: {NOW}",
        "-- ============================================================",
        "",
    ]

    lines.append("-- ── 1. UPDATE products table ──────────────────────────────────")
    lines.append("")

    for r in results:
        category  = r['category']
        real_name = r['real_name']
        pid       = r['product_id']
        sku       = generate_sku(category, real_name)
        desc      = f"{category} product: {real_name[:80]}"

        lines.append(f"-- [{category}] {r['synthetic_name']} → {real_name[:50]}")
        lines.append(f"UPDATE public.products")
        lines.append(f"SET   product_name  = '{esc(real_name)}',")
        lines.append(f"      description   = '{esc(desc)}',")
        lines.append(f"      sku           = '{esc(sku)}',")
        lines.append(f"      is_synthetic  = FALSE,")
        lines.append(f"      updated_at    = '{NOW}'")
        lines.append(f"WHERE product_id = '{pid}';")
        lines.append("")

    lines.append("-- ── 2. UPDATE / INSERT product_image rows ─────────────────────")
    lines.append("")

    for r in results:
        category    = r['category']
        real_name   = r['real_name']
        pid         = r['product_id']
        img_sort1   = r['img_sort1_id']
        url_base    = url_encode_path(category, real_name)

        lines.append(f"-- [{category}] {real_name[:55]}")

        # sort_order 1 — UPDATE existing row
        lines.append(f"UPDATE product_image")
        lines.append(f"SET   image_url = '{url_base}/image_1.jpg',")
        lines.append(f"      alt_text  = '{esc(real_name)} - image 1',")
        lines.append(f"      created_at = '{NOW}'")
        lines.append(f"WHERE product_image_id = '{img_sort1}';")
        lines.append("")

        # sort_order 2-5 — INSERT (ON CONFLICT update)
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
            lines.append(
                f"ON CONFLICT (product_id, sort_order)"
            )
            lines.append(
                f"DO UPDATE SET image_url = EXCLUDED.image_url,"
                f" alt_text = EXCLUDED.alt_text;"
            )
            lines.append("")

    lines.append(f"-- Total: {len(results)} products replaced")
    return "\n".join(lines)


def main():
    session = make_session()

    # Warm up
    print("Warming up session...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        sleep(2, 4)
    except Exception as e:
        print(f"  Warning: {e}")

    results = []
    failed  = []

    for (syn_name, category, category_id, product_id,
         img_sort1_id, search_query) in SYNTHETIC_PRODUCTS:

        result = process_product(
            session, syn_name, category, category_id,
            product_id, img_sort1_id, search_query
        )

        if result:
            results.append(result)
        else:
            failed.append(syn_name)

        # Rotate user agent
        session.headers['User-Agent'] = random.choice(USER_AGENTS)
        sleep(4, 8)

    # Generate SQL
    if results:
        sql = build_sql(results)
        os.makedirs(os.path.dirname(SQL_OUT), exist_ok=True)
        with open(SQL_OUT, 'w', encoding='utf-8') as f:
            f.write(sql)
        print(f"\n✓ SQL written to: {SQL_OUT}")
    else:
        print("\n✗ No products processed — SQL not written.")

    print(f"\n{'='*65}")
    print(f"  Replaced: {len(results)}/19 products")
    if failed:
        print(f"  Failed:   {', '.join(failed)}")
    print(f"{'='*65}")

    # Print summary table
    print("\nSummary:")
    for r in results:
        print(f"  ✓ {r['synthetic_name'][:35]:<35} → {r['real_name'][:45]}")
    for f in failed:
        print(f"  ✗ {f}")


if __name__ == "__main__":
    main()
