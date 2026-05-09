"""
Amazon.ca product image scraper.
Downloads 12-15 products per category with 5 images each.
"""

import requests
from bs4 import BeautifulSoup
import os
import time
import re
import json
import random
from urllib.parse import urljoin

# ── Configuration ────────────────────────────────────────────────────────────

IMAGE_BASE = r"D:\a\crm_agent\image"
TARGET_PRODUCTS = 13          # aim for 13 per category
IMAGES_PER_PRODUCT = 5
DELAY_MIN = 2.5               # seconds between page requests
DELAY_MAX = 5.0

# Search queries for each category
CATEGORY_QUERIES = {
    "Apparel":             "women men clothing tops jeans hoodie jacket",
    "Electronics":         "best selling electronics canada",
    "Grocery":             "popular grocery food items canada",
    "Health & Wellness":   "health wellness supplements fitness canada",
    "Home Essentials":     "home essentials kitchen cleaning decor canada",
    "Office Supplies":     "office supplies stationery accessories canada",
    "Personal Care":       "personal care hygiene grooming canada",
    "Pet Supplies":        "pet supplies food toys grooming canada",
    "Snacks & Beverages":  "popular snacks drinks beverages canada",
    "Toys & Games":        "best selling toys games kids canada",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

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


def sleep():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def sanitize(name: str) -> str:
    """Make a string safe for use as a Windows folder name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.rstrip(' ,.')   # remove trailing punctuation Windows dislikes
    return name[:120]


def get_existing_products(category_folder: str) -> set:
    if not os.path.exists(category_folder):
        return set()
    return {
        d for d in os.listdir(category_folder)
        if os.path.isdir(os.path.join(category_folder, d))
    }


def count_images(folder: str) -> int:
    if not os.path.exists(folder):
        return 0
    return sum(
        1 for f in os.listdir(folder)
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
    )


def download_image(session, url: str, dest_path: str) -> bool:
    try:
        r = session.get(url, timeout=20, stream=True)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(dest_path, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"    [img error] {e}")
    return False


# ── Amazon scraping ───────────────────────────────────────────────────────────

def fetch_page(session, url: str, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 503:
                print(f"  503 – waiting 10 s (attempt {attempt+1})")
                time.sleep(10)
            else:
                print(f"  HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"  Request error: {e}")
        time.sleep(5)
    return None


def search_products(session, query: str, page: int = 1) -> list[dict]:
    """Return list of {title, url, asin} from an Amazon.ca search results page."""
    encoded = query.replace(' ', '+')
    url = f"https://www.amazon.ca/s?k={encoded}&page={page}"
    html = fetch_page(session, url)
    if not html:
        return []

    soup = BeautifulSoup(html, 'lxml')
    results = []

    # Each product card
    for card in soup.select('[data-component-type="s-search-result"]'):
        asin = card.get('data-asin', '')
        if not asin:
            continue
        # Try to get full product title
        title_tag = card.select_one('h2 a span') or card.select_one('h2 span') or card.select_one('.a-text-normal')
        h2_link = card.select_one('h2 a')
        if h2_link and h2_link.get('aria-label'):
            title = h2_link['aria-label'].strip()
        elif title_tag:
            title = title_tag.get_text(strip=True)
        else:
            title = ''

        # Find product URL (look for any /dp/ link in the card)
        link_tag = card.select_one('h2 a.a-link-normal') or card.select_one('a[href*="/dp/"]')
        if link_tag and link_tag.get('href'):
            href = link_tag['href']
        else:
            href = f"/dp/{asin}"
        product_url = urljoin("https://www.amazon.ca", href.split('?')[0])

        # If title is just a brand name, extract from URL path
        if len(title) < 15:
            m = re.search(r'/([^/]+)/dp/', href)
            if m:
                url_name = m.group(1).replace('-', ' ').strip()
                if len(url_name) > len(title):
                    title = url_name

        if len(title) < 10:
            continue
        results.append({'title': title, 'url': product_url, 'asin': asin})

    return results


def get_product_images(session, product_url: str) -> list[str]:
    """Return up to IMAGES_PER_PRODUCT high-res image URLs from a product page."""
    html = fetch_page(session, product_url)
    if not html:
        return []

    soup = BeautifulSoup(html, 'lxml')
    image_urls = []

    # Strategy 1: colorImages JSON blob in page scripts
    for script in soup.find_all('script'):
        text = script.string or ''
        if "'colorImages'" in text or '"colorImages"' in text or 'ImageBlockATF' in text:
            # Extract all high-res image URLs
            found = re.findall(r'"hiRes"\s*:\s*"(https://[^"]+)"', text)
            if found:
                image_urls.extend(found)
            if not image_urls:
                found = re.findall(r'"large"\s*:\s*"(https://[^"]+)"', text)
                image_urls.extend(found)
            if image_urls:
                break

    # Strategy 2: data-a-dynamic-image attribute
    if not image_urls:
        for img in soup.select('img[data-a-dynamic-image]'):
            data = img.get('data-a-dynamic-image', '{}')
            try:
                urls = list(json.loads(data).keys())
                image_urls.extend(urls)
            except Exception:
                pass

    # Strategy 3: main product image + altImages thumbnails
    if not image_urls:
        main = soup.select_one('#landingImage, #imgBlkFront')
        if main:
            src = main.get('data-old-hires') or main.get('src', '')
            if src:
                image_urls.append(src)
        for thumb in soup.select('#altImages img'):
            src = thumb.get('src', '')
            # Convert thumbnail URL to high-res
            src = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', src)
            if src.startswith('https://') and 'sprite' not in src:
                image_urls.append(src)

    # Deduplicate and clean
    seen = set()
    clean = []
    for u in image_urls:
        u = u.strip()
        if u and u not in seen and 'sprite' not in u and u.startswith('http'):
            seen.add(u)
            clean.append(u)

    return clean[:IMAGES_PER_PRODUCT]


# ── Main processing ───────────────────────────────────────────────────────────

def process_category(session, category: str, query: str):
    category_folder = os.path.join(IMAGE_BASE, category)
    os.makedirs(category_folder, exist_ok=True)

    existing = get_existing_products(category_folder)
    needed = TARGET_PRODUCTS - len(existing)
    print(f"\n{'='*60}")
    print(f"Category: {category}  (have {len(existing)}, need {needed} more)")
    print(f"{'='*60}")

    if needed <= 0:
        print("  Already complete, skipping.")
        return

    products_added = 0
    page = 1

    while products_added < needed and page <= 5:
        print(f"\n  Searching page {page} for: {query}")
        sleep()
        candidates = search_products(session, query, page)
        print(f"  Found {len(candidates)} candidates")

        for prod in candidates:
            if products_added >= needed:
                break

            folder_name = sanitize(prod['title'])
            if folder_name in existing:
                print(f"  [skip] {folder_name[:60]}...")
                continue

            product_folder = os.path.join(category_folder, folder_name)
            already = count_images(product_folder)
            if already >= IMAGES_PER_PRODUCT:
                print(f"  [skip-done] {folder_name[:60]}")
                existing.add(folder_name)
                continue

            print(f"\n  Product: {prod['title'][:70]}")
            sleep()
            image_urls = get_product_images(session, prod['url'])
            print(f"  Found {len(image_urls)} images")

            if not image_urls:
                print("  No images found, skipping product.")
                continue

            os.makedirs(product_folder, exist_ok=True)
            downloaded = already
            for i, img_url in enumerate(image_urls):
                if downloaded >= IMAGES_PER_PRODUCT:
                    break
                ext = '.jpg'
                m = re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', img_url, re.I)
                if m:
                    ext = '.' + m.group(1).lower()
                fname = os.path.join(product_folder, f"image_{downloaded+1}{ext}")
                ok = download_image(session, img_url, fname)
                if ok:
                    downloaded += 1
                    print(f"    Downloaded {downloaded}/{IMAGES_PER_PRODUCT}")

            if downloaded >= 3:   # accept partial (at least 3 images)
                products_added += 1
                existing.add(folder_name)
                print(f"  + Added '{folder_name[:60]}' ({downloaded} imgs) [{products_added}/{needed}]")
            else:
                print(f"  Only {downloaded} images, removing folder.")
                try:
                    import shutil
                    shutil.rmtree(product_folder)
                except Exception:
                    pass

        page += 1

    print(f"\n  Done with {category}: added {products_added} products.")


def main():
    session = make_session()

    # Warm up: visit homepage first to get cookies
    print("Warming up session...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        time.sleep(2)
    except Exception as e:
        print(f"  Warning: {e}")

    # Only process categories that still need products
    only_run = {"Apparel"}  # set to empty set {} to run all
    for category, query in CATEGORY_QUERIES.items():
        if only_run and category not in only_run:
            continue
        category_folder = os.path.join(IMAGE_BASE, category)
        existing = get_existing_products(category_folder)
        needed = TARGET_PRODUCTS - len(existing)
        if needed > 0:
            process_category(session, category, query)
            # Rotate user agent between categories
            session.headers['User-Agent'] = random.choice(USER_AGENTS)
            time.sleep(random.uniform(5, 10))
        else:
            print(f"[OK] {category}: already has {len(existing)} products")

    print("\n\nAll done!")


if __name__ == "__main__":
    main()
