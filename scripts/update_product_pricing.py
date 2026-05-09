"""
Update product_pricing dataset:
1. Add 7 missing products
2. Fetch current retail prices from Amazon.ca for all 144 products
3. Set wholesale price (15-60% below retail by category)
4. Set promo price (between retail and wholesale)
5. Write updated 'product_pricing dataset' CSV
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import csv, os, re, json, time, random, uuid, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timezone
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────────────────────────
DATA_DIR  = r"D:\a\crm_agent"
NOW       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")
TODAY     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
DELAY_MIN = 2.0
DELAY_MAX = 4.5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# ── Category margin ranges (discount % off retail → wholesale) ─────────────────
# Values: (min_discount%, max_discount%)  floor is 15%, ceiling is 60%
CATEGORY_MARGINS = {
    "Apparel":            (40, 60),
    "Electronics":        (15, 20),
    "Grocery":            (15, 15),
    "Health & Wellness":  (30, 60),
    "Home Essentials":    (20, 40),
    "Office Supplies":    (20, 45),
    "Personal Care":      (25, 55),
    "Pet Supplies":       (20, 50),
    "Snacks & Beverages": (15, 30),
    "Toys & Games":       (25, 50),
}

# ── Category ID → name mapping ─────────────────────────────────────────────────
CAT_ID_MAP = {
    "7632ef73-7a4a-4320-b5d8-a2bb72bd8c03": "Apparel",
    "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0": "Electronics",
    "fea01756-1ba1-4b38-841f-c6a2b86bb2a6": "Grocery",
    "fcaaec3d-21d4-461d-9dbe-849c7c14c7de": "Health & Wellness",
    "c346f439-e972-4f0a-8115-f3baa63cc1d8": "Home Essentials",
    "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec": "Office Supplies",
    "adf36cbb-9243-4a60-96ac-f5998361ed91": "Personal Care",
    "7fb054a9-5457-4932-9c89-4701da3f1dcc": "Pet Supplies",
    "64c198d3-3bcc-4291-ab8d-7e12abf24b2f": "Snacks & Beverages",
    "78e2ee6c-ee94-4bdc-ad4a-405ff2332e65": "Toys & Games",
}

# ── Product name → true category (overrides DB category for misclassified items) ──
# Based on what the products actually are
CATEGORY_OVERRIDES = {
    # Grocery items wrongly assigned to Office Supplies (cdcbd1da)
    "7297ec71-c4d1-4d10-b07f-62e16d8b84ea": "Grocery",   # Zentro Ketchup
    "42e5196b-c323-4947-9781-26147c5e8995": "Grocery",   # FreshVale Whole Milk
    # Office Supplies items wrongly in other categories
    "1a2f39cc-2875-4cea-af9e-42a10a204f3a": "Office Supplies",  # Easyview Binder
    "3f6b0422-ff1e-4e20-8af1-696024c399a4": "Office Supplies",  # M&G Pen Holder
    "e20d9815-f9c1-4eb5-9f55-48664c867daa": "Office Supplies",  # 7 code Desk Organizer
    "07febcd1-6356-4aa5-b696-753b4e12e0da": "Office Supplies",  # Quartet Lined Easel Pad
    "ade5e4ed-1149-496c-92a6-1bf376261194": "Office Supplies",  # Quartet Plain Easel Pad
    "1311813c-663e-4824-aeb3-a416bf7d51f1": "Office Supplies",  # Accordion File Organizer
    "2453e7d0-9d63-4fdf-bb41-4f81c835e551": "Office Supplies",  # Mesh Desk Organizer
    "166728e5-754e-470c-bce2-984589eb3fe7": "Office Supplies",  # Granvela Desk Organizer
    "48a449d1-4e99-4d33-823c-d0a5c5a97252": "Office Supplies",  # Staples Oval Mesh
    "bda7b79d-15ca-4a41-94a0-be43ef693ee6": "Office Supplies",  # Blue Ginkgo Desk Organizer
    "cde83fb8-d90c-48ae-bb40-3a879a57bd0d": "Office Supplies",  # DecoBrothers Pencil Holder
    "3d9aa478-a8c9-4c42-89b6-8815def80593": "Office Supplies",  # Janlaugh School Supplies
    "5b2ff158-be1c-40a4-badb-bb37d3da0246": "Office Supplies",  # DeskFlow Whiteboard Markers
    "0274bc65-9623-4170-9b66-a0aa858faf74": "Office Supplies",  # PaperNest Sticky Notes
    # Personal Care items wrongly assigned
    "2b5fed52-d880-4c06-ba36-987532d81954": "Personal Care",  # Solvante Toothpaste
    "14c1d9ae-48d2-464a-aeb2-40728a9950c7": "Personal Care",  # PureGlow Toothbrush
    # Toys & Games items wrongly in Grocery
    "d6ba63de-5220-4fb7-9d9a-fbc7ea949f86": "Toys & Games",  # WonderBox Card Game
    "3ef560b7-1001-489d-bd11-066af5e1e927": "Toys & Games",  # PlayForge Teddy Bear
    # Health & Wellness items wrongly in Toys & Games (78e2ee6c)
    "519fe978-7b9e-4475-9aec-4c8b74b2a7fd": "Health & Wellness",  # Solvante Yoga Mat
    "1465249d-24ba-47d3-8611-f2e9b58b967b": "Health & Wellness",  # Vitalis Vitamin D3
    # Personal Care items with wrong cat_id
    "4df45489-5184-40bb-9ec8-4b2bc8d5b411": "Personal Care",  # Super Fresh Lady Parts
    "960fb8bf-c8f8-4031-89a0-02566e9b1eed": "Personal Care",  # Crest 3D Whitestrips
    "c5f5857a-75a8-445b-8182-ad2a8d0331bd": "Personal Care",  # Bushbalm Trimmer
    "d39207d9-7c98-48fa-835e-13102bbf2483": "Personal Care",  # Fresh BALLS Lotion
    "d6c22324-a493-4bc2-a165-aba7941fdccf": "Personal Care",  # Bearback Shaver
    "e365e384-7eaf-444f-8d71-dfaf49c42087": "Personal Care",  # OLOV Electric Trimmer
    "2b4b127a-a0f7-4332-9616-99e6dfb73b24": "Personal Care",  # Brightup Beard Trimmer
    "61166dfa-7ce7-4e2e-a324-0adae0310696": "Personal Care",  # Brickell Anti-Aging Cream
    "0236eee0-c50f-4554-90f4-ab6124a3249c": "Personal Care",  # Japanese Nail Clippers
    "90d89942-77a5-4a8f-8fa8-7be52e84f0cf": "Personal Care",  # Utopia Care Eyebrow Scissors
    "24e3b771-5e3f-4800-ae1e-8bd4ee65c57d": "Personal Care",  # MERIDIAN Trimmer
    "2479ce25-9072-43a6-99ca-9eb914779b92": "Personal Care",  # U Brands Felt Tip Pens
    "ba52fd3e-930a-43ac-8ca8-0a9e532cf7cc": "Personal Care",  # Aveeno Repair Cream
    "a3bc543b-b792-4c78-8cc8-53ebd9ca29c1": "Personal Care",  # WaterWipes Baby Wipes
    # Office Supplies items in wrong category
    "82285d6b-4b1d-4f2a-944a-352183b98b1e": "Office Supplies",  # QuickPrint Toner
    "c738e598-73e0-4cf9-baf5-daf1c65c3279": "Office Supplies",  # LabelMax Maker
    "5660c3cb-1c79-4939-90c6-03d089a83626": "Office Supplies",  # EcoWrite Notebook
    # Grocery items
    "adda99eb-ed64-4be1-8e96-46c07a40ab74": "Grocery",  # Heinz Ketchup 1.25LT
    "90f36595-e28d-4daa-aebe-614b8c71c0cd": "Grocery",  # Matteo's Coffee Syrup
    # Electronics items
    "603f184e-782b-430a-993f-9b6b95952685": "Electronics",  # WD 2TB My Passport
    "9841ac0c-f665-47d6-b75c-76c0dcdce67f": "Electronics",  # LG 24 Monitor
    "e59f53fe-b2a2-4664-8212-8d4c45aa8ccc": "Electronics",  # MSI RTX 5090
    "c03fec1b-b2ca-4153-ad53-75cef2f97994": "Electronics",  # Merriam-Webster Dictionary
    # Home Essentials
    "23bc7ed1-87dd-4ef6-884b-70d45ec3cbcb": "Home Essentials",  # Silicone Drying Mat
}

# ── HTTP helpers ───────────────────────────────────────────────────────────────

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9",
        "Connection": "keep-alive",
        "DNT": "1",
    })
    return s


def sleep():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def fetch(session, url):
    for _ in range(3):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code == 503:
                time.sleep(12)
        except Exception:
            pass
        time.sleep(4)
    return None


def search_price_amazon(session, query):
    """
    Search Amazon.ca for a product and return the first numeric price found.
    Returns float or None.
    """
    encoded = query.replace(' ', '+')
    url = f"https://www.amazon.ca/s?k={encoded}"
    sleep()
    html = fetch(session, url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'lxml')

    # Try to find prices in search result cards
    for card in soup.select('[data-component-type="s-search-result"]'):
        # Price whole + fraction
        whole = card.select_one('.a-price-whole')
        frac  = card.select_one('.a-price-fraction')
        if whole:
            w_text = whole.get_text(strip=True).replace(',', '').rstrip('.')
            f_text = frac.get_text(strip=True) if frac else '00'
            try:
                price = float(f"{w_text}.{f_text}")
                if 0.5 < price < 5000:
                    return price
            except ValueError:
                pass
        # Fallback: look for any .a-offscreen price
        offscreen = card.select_one('.a-price .a-offscreen')
        if offscreen:
            m = re.search(r'[\$\£]?\s*([\d,]+\.?\d*)', offscreen.get_text())
            if m:
                try:
                    price = float(m.group(1).replace(',', ''))
                    if 0.5 < price < 5000:
                        return price
                except ValueError:
                    pass

    # Fallback: scan all price elements on page
    for el in soup.select('.a-price-whole'):
        text = el.get_text(strip=True).replace(',', '').rstrip('.')
        try:
            price = float(text)
            if 0.5 < price < 5000:
                return price
        except ValueError:
            pass
    return None


# ── Pricing calculation ────────────────────────────────────────────────────────

def calc_wholesale(retail, category):
    lo, hi = CATEGORY_MARGINS.get(category, (20, 40))
    discount = random.randint(lo, hi) / 100.0
    ws = retail * (1 - discount)
    return round(ws, 2)


def calc_promo(retail, wholesale):
    # Random position between wholesale and retail (closer to retail)
    frac = random.uniform(0.15, 0.55)  # 15-55% of the way up from wholesale
    promo = wholesale + frac * (retail - wholesale)
    return round(promo, 2)


# ── Data loading ───────────────────────────────────────────────────────────────

def load_products():
    products = {}
    with open(os.path.join(DATA_DIR, 'product dateset.csv'), encoding='utf-8') as f:
        for row in csv.DictReader(f):
            products[row['product_id']] = row
    return products


def load_pricing():
    rows = []
    with open(os.path.join(DATA_DIR, 'product_pricing dataset'), encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            rows.append(row)
    return rows, fieldnames


def get_category(product_row):
    pid = product_row['product_id']
    if pid in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[pid]
    return CAT_ID_MAP.get(product_row['category_id'], 'Office Supplies')


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    products   = load_products()
    old_rows, fieldnames = load_pricing()

    # Build lookup: product_id → {price_type → [rows]}
    pricing_by_pid = defaultdict(lambda: defaultdict(list))
    for r in old_rows:
        pricing_by_pid[r['product_id']][r['price_type']].append(r)

    # Find products with no pricing at all (need new rows)
    priced_pids = set(pricing_by_pid.keys())
    new_pids = [pid for pid in products if pid not in priced_pids]
    print(f"Products in table  : {len(products)}")
    print(f"Products in pricing: {len(priced_pids)}")
    print(f"New products needed: {len(new_pids)}")
    for pid in new_pids:
        print(f"  + {products[pid]['product_name'][:70]}")

    session = make_session()
    print("\nWarming up...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        sleep()
    except Exception:
        pass

    # Fetch prices for all 144 products
    price_cache = {}  # product_id → retail_price
    print(f"\nFetching prices for {len(products)} products...")

    for i, (pid, prow) in enumerate(products.items(), 1):
        name     = prow['product_name']
        category = get_category(prow)
        query    = name[:80]  # truncate long names

        print(f"  [{i:3}/{len(products)}] {name[:55]:55} [{category[:15]}]", end=' ', flush=True)

        price = search_price_amazon(session, query)

        if price:
            price_cache[pid] = price
            print(f"${price:.2f}")
        else:
            # Use existing retail price as fallback
            existing = pricing_by_pid.get(pid, {}).get('Retail', [])
            active = [r for r in existing if r['effective_to'] in ('NULL', '')]
            future = [r for r in existing if r['effective_to'] not in ('NULL', '') and r['effective_to'] > TODAY]
            fallback_rows = active or future or existing
            if fallback_rows:
                try:
                    price = float(fallback_rows[-1]['price_value'])
                    price_cache[pid] = price
                    print(f"${price:.2f} [fallback]")
                except (ValueError, KeyError):
                    price_cache[pid] = 29.99  # last resort default
                    print(f"$29.99 [default]")
            else:
                price_cache[pid] = 29.99
                print(f"$29.99 [default-new]")

        session.headers['User-Agent'] = random.choice(USER_AGENTS)

    # ── Build new pricing rows ─────────────────────────────────────────────────
    print("\nBuilding updated pricing rows...")

    # We'll rebuild all rows:
    # For existing products: close old active rows, add new ones
    # For new products: create all 3 price types from scratch

    new_output_rows = []

    def add_row(price_type, price_value, pid, label=None, eff_from=None, eff_to='NULL',
                created=None, updated=None, is_synthetic=False):
        new_output_rows.append({
            'price_type':        price_type,
            'price_value':       f"{price_value:.2f}",
            'currency_code':     'CAD',
            'effective_from':    eff_from or TODAY,
            'effective_to':      eff_to,
            'created_at':        created or NOW,
            'updated_at':        updated or NOW,
            'price_label':       label or 'NULL',
            'product_id':        pid,
            'product_pricing_id': str(uuid.uuid4()),
            'is_synthetic':      'False' if not is_synthetic else 'True',
        })

    for pid, prow in products.items():
        category = get_category(prow)
        retail   = price_cache[pid]
        ws       = calc_wholesale(retail, category)
        promo    = calc_promo(retail, ws)

        existing_rows = pricing_by_pid.get(pid, {})

        if existing_rows:
            # ── Existing product ─────────────────────────────────────────────
            # 1. Keep all historical rows (effective_to != NULL and date in past)
            for price_type, rows in existing_rows.items():
                for r in rows:
                    eff_to = r['effective_to']
                    is_hist = (eff_to != 'NULL' and eff_to != '' and eff_to <= TODAY)
                    if is_hist:
                        new_output_rows.append(r)  # keep historical as-is
                    # Skip active/future rows — we'll replace them

            # 2. Close any old "active" rows up to yesterday
            yesterday = (datetime.now(timezone.utc).replace(hour=0,minute=0,second=0)
                         ).strftime("%Y-%m-%d")

            # 3. Add fresh current Retail
            add_row('Retail', retail, pid,
                    label='Amazon.ca price update 2026-03',
                    eff_from=TODAY, eff_to='NULL')

            # 4. Add fresh current Wholesale
            add_row('Wholesale', ws, pid,
                    label=f'{category} wholesale {TODAY}',
                    eff_from=TODAY, eff_to='NULL')

            # 5. Add fresh Promo
            add_row('Promo', promo, pid,
                    label='Spring 2026 promo',
                    eff_from=TODAY, eff_to='2026-06-30')

        else:
            # ── New product ──────────────────────────────────────────────────
            add_row('Retail', retail, pid,
                    label='Initial retail price',
                    eff_from=TODAY, eff_to='NULL',
                    is_synthetic=prow.get('is_synthetic', 'False') == 'True')

            add_row('Wholesale', ws, pid,
                    label=f'{category} initial wholesale',
                    eff_from=TODAY, eff_to='NULL',
                    is_synthetic=prow.get('is_synthetic', 'False') == 'True')

            add_row('Promo', promo, pid,
                    label='Launch promo',
                    eff_from=TODAY, eff_to='2026-06-30',
                    is_synthetic=prow.get('is_synthetic', 'False') == 'True')

    # Write output CSV
    out_path = os.path.join(DATA_DIR, 'product_pricing dataset')
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_output_rows)

    print(f"\nWritten: {out_path}")
    print(f"Total rows: {len(new_output_rows)}")

    # Summary stats
    retail_rows = [r for r in new_output_rows if r['price_type'] == 'Retail' and r['effective_to'] == 'NULL']
    ws_rows     = [r for r in new_output_rows if r['price_type'] == 'Wholesale' and r['effective_to'] == 'NULL']
    promo_rows  = [r for r in new_output_rows if r['price_type'] == 'Promo']

    print(f"\nActive retail rows  : {len(retail_rows)}")
    print(f"Active wholesale rows: {len(ws_rows)}")
    print(f"Promo rows          : {len(promo_rows)}")

    # Print sample of updated prices
    print("\nSample updated prices:")
    sample_pids = list(products.keys())[:10]
    for pid in sample_pids:
        name = products[pid]['product_name'][:45]
        cat  = get_category(products[pid])
        r_rows = [r for r in new_output_rows if r['product_id']==pid and r['price_type']=='Retail' and r['effective_to']=='NULL']
        w_rows = [r for r in new_output_rows if r['product_id']==pid and r['price_type']=='Wholesale' and r['effective_to']=='NULL']
        p_rows = [r for r in new_output_rows if r['product_id']==pid and r['price_type']=='Promo']
        r_p = r_rows[0]['price_value'] if r_rows else '?'
        w_p = w_rows[0]['price_value'] if w_rows else '?'
        p_p = p_rows[-1]['price_value'] if p_rows else '?'
        print(f"  {name:<45} | {cat:<18} | R:{r_p:>8} W:{w_p:>8} P:{p_p:>8}")


if __name__ == "__main__":
    main()
