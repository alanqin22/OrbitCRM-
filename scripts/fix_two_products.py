"""Fix wrong matches: UltraSharp (got cable) and LabelMax (got label tape)."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from bs4 import BeautifulSoup
import os, re, json, time, random, shutil, uuid
from urllib.parse import urljoin, quote
from datetime import datetime, timezone

IMAGE_BASE = r"D:\a\crm_agent\image"
IMAGES_PER = 5
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
        "Connection": "keep-alive",
    })
    return s

def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:50].rstrip(' ,.;-')

def sleep(lo=2.5, hi=5.0):
    time.sleep(random.uniform(lo, hi))

def fetch(session, url):
    for _ in range(3):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 503:
                time.sleep(15)
        except Exception as e:
            print(f"  Error: {e}")
        time.sleep(5)
    return None

def search_amazon(session, query, skip_keywords=None):
    """Search and skip results containing any skip_keywords."""
    skip_keywords = skip_keywords or []
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
        # Skip unwanted product types
        title_lower = title.lower()
        if any(kw in title_lower for kw in skip_keywords):
            continue
        link_tag = card.select_one('h2 a.a-link-normal') or card.select_one('a[href*="/dp/"]')
        href = link_tag['href'] if link_tag and link_tag.get('href') else f'/dp/{asin}'
        product_url = urljoin("https://www.amazon.ca", href.split('?')[0])
        if len(title) >= 15:
            results.append({'title': title, 'url': product_url})
    return results

def get_images(session, url):
    sleep()
    html = fetch(session, url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'lxml')
    urls = []
    for script in soup.find_all('script'):
        text = script.string or ''
        if "'colorImages'" in text or '"colorImages"' in text or 'ImageBlockATF' in text:
            found = re.findall(r'"hiRes"\s*:\s*"(https://[^"]+)"', text)
            if not found:
                found = re.findall(r'"large"\s*:\s*"(https://[^"]+)"', text)
            urls.extend(found)
            if urls:
                break
    if not urls:
        for img in soup.select('img[data-a-dynamic-image]'):
            try:
                urls.extend(list(json.loads(img.get('data-a-dynamic-image', '{}')).keys()))
            except Exception:
                pass
    seen, clean = set(), []
    for u in urls:
        if u not in seen and 'sprite' not in u and u.startswith('http'):
            seen.add(u)
            clean.append(u)
    return clean[:IMAGES_PER]

def download(session, url, path):
    try:
        r = session.get(url, timeout=20, stream=True)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(path, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"    Error: {e}")
    return False


def scrape_one(session, category, query, skip_keywords=None):
    candidates = search_amazon(session, query, skip_keywords)
    if not candidates:
        return None, None
    prod = candidates[0]
    real_name = sanitize(prod['title'])
    print(f"  Selected: {real_name}")
    imgs = get_images(session, prod['url'])
    print(f"  Images: {len(imgs)}")
    if not imgs:
        return None, None
    folder = os.path.join(IMAGE_BASE, category, real_name)
    os.makedirs(folder, exist_ok=True)
    n = 0
    for img_url in imgs:
        if n >= IMAGES_PER:
            break
        if download(session, img_url, os.path.join(folder, f"image_{n+1}.jpg")):
            n += 1
            print(f"    {n}/{IMAGES_PER}")
    if n < 3:
        shutil.rmtree(folder, ignore_errors=True)
        return None, None
    img1 = os.path.join(folder, 'image_1.jpg')
    for i in range(n + 1, IMAGES_PER + 1):
        dest = os.path.join(folder, f'image_{i}.jpg')
        if not os.path.exists(dest):
            shutil.copy2(img1, dest)
    print(f"  + Saved to: {folder}")
    return real_name, folder


def main():
    session = make_session()
    session.get("https://www.amazon.ca", timeout=15)
    sleep(2, 4)

    fixes = {}

    # --- Fix 1: UltraSharp 27" 4K Monitor ---
    # Remove wrong folder
    wrong1 = os.path.join(IMAGE_BASE, "Electronics", "4K HDMI 2.0 Cable 10FT 5-Pack, High Speed 18Gbps H")
    if os.path.isdir(wrong1):
        shutil.rmtree(wrong1)
        print(f"Removed wrong folder: {wrong1}")

    print("\n[1/2] Finding 27-inch 4K monitor...")
    name1, _ = scrape_one(
        session, "Electronics",
        "27 inch 4K monitor IPS display HDMI displayport",
        skip_keywords=["cable", "cord", "adapter", "sleeve", "stand", "hub", "docking"]
    )
    if not name1:
        # Try alternate query
        sleep(3, 6)
        name1, _ = scrape_one(
            session, "Electronics",
            "computer monitor 27 4K UHD HDMI",
            skip_keywords=["cable", "cord", "adapter", "hub"]
        )
    if name1:
        fixes['UltraSharp'] = name1
        print(f"  Fixed: {name1}")
    session.headers['User-Agent'] = random.choice(USER_AGENTS)
    sleep(4, 7)

    # --- Fix 2: LabelMax Pro Label Maker ---
    # Remove wrong folder
    wrong2 = os.path.join(IMAGE_BASE, "Office Supplies", "Replace DYMO D1 Label Tape 45013 S0720530 D1 Refil")
    if os.path.isdir(wrong2):
        shutil.rmtree(wrong2)
        print(f"\nRemoved wrong folder: {wrong2}")

    print("\n[2/2] Finding label maker...")
    name2, _ = scrape_one(
        session, "Office Supplies",
        "label maker thermal handheld DYMO",
        skip_keywords=["tape", "refill", "cartridge", "ribbon", "labels", "replacement", "compatible"]
    )
    if not name2:
        sleep(3, 6)
        name2, _ = scrape_one(
            session, "Office Supplies",
            "label printer maker handheld portable",
            skip_keywords=["tape", "refill", "cartridge", "ribbon", "replacement"]
        )
    if name2:
        fixes['LabelMax'] = name2
        print(f"  Fixed: {name2}")

    # Print results
    print("\n--- Fix Summary ---")
    for k, v in fixes.items():
        print(f"  {k}: {v}")

    if fixes:
        print("\nRe-run replace_synthetic_remaining.py to regenerate SQL with corrected folder names.")
        print("Or update the COMPLETED list manually in replace_synthetic_remaining.py.")


if __name__ == "__main__":
    main()
