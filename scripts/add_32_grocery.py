"""
Add 32 best-selling Grocery products:
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally  → image/Grocery/{Folder Name}/image_N.jpg
  3. Uploads to agentorc.ca using UNENCODED folder names (spaces, not %20)
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)
  5. Generates sql/insert_32_grocery.sql from live DB data

Run from project root:
    python scripts/add_32_grocery.py
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os, re, json, time, random, uuid, requests
from urllib.parse import quote, urljoin
from datetime import datetime, timezone
import psycopg2
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────
IMAGE_BASE   = r"D:\a\crm_agent\image"
SQL_OUT      = r"D:\a\crm_agent\sql\insert_32_grocery.sql"
IMAGES_PER   = 5
DELAY_MIN    = 2.0
DELAY_MAX    = 4.5
NOW          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
REMOTE_BASE  = "/home2/agentorc/public_html/image"

DB_HOST = "shinkansen.proxy.rlwy.net"
DB_PORT = 26832
DB_NAME = "railway"
DB_USER = "postgres"
DB_PASS = "SimKpntYtoGdLWdVsXglunQqHZMHXUfQ"

GROCERY_CAT_ID = "fea01756-1ba1-4b38-841f-c6a2b86bb2a6"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 32 Best-selling Grocery products ─────────────────────────────────────────
# (product_number, sku, retail_cad, ws_pct, promo_ratio, stock,
#  full_product_name, folder_name, description, amazon_search_query)
PRODUCTS = [
    (239, 'GRO-FOLG-CLAS-021', 18.99, 0.18, 0.48, 420,
     "Folgers Classic Roast Ground Coffee, 1.36 kg",
     "Folgers Classic Roast Ground Coffee 1.36 kg",
     "Folgers Classic Roast is the mountain grown coffee that's perfectly roasted for a "
     "smooth, rich flavour with a mild body. This large 1.36 kg canister provides roughly "
     "270 cups of coffee and is made from a blend of 100% pure coffee beans roasted to a "
     "classic medium roast. Ideal for drip coffee makers.",
     "Folgers classic roast ground coffee"),

    (240, 'GRO-MAXW-ORIG-022', 16.99, 0.18, 0.48, 385,
     "Maxwell House Original Roast Ground Coffee, 925 g",
     "Maxwell House Original Roast Ground Coffee 925g",
     "Maxwell House Original Roast delivers a consistently smooth, full-bodied flavour in "
     "every cup. Made from 100% pure coffee, this 925 g can provides a classic medium roast "
     "that's been a household favourite for generations. Compatible with all standard drip "
     "coffee makers for a reliable morning brew.",
     "Maxwell House original roast coffee"),

    (241, 'GRO-NESC-GOLD-023', 14.99, 0.18, 0.50, 350,
     "Nescafe Gold Blend Instant Coffee 200g",
     "Nescafe Gold Blend Instant Coffee 200g",
     "Nescafe Gold Blend Instant Coffee is crafted from a blend of premium Arabica and "
     "Robusta beans that are gently roasted to preserve their rich aromas and flavours. "
     "Each cup delivers a velvety smooth taste with a warm, golden colour. Simply add hot "
     "water for a perfectly balanced cup in seconds, any time of day.",
     "Nescafe gold instant coffee"),

    (242, 'GRO-TETL-ORAN-024', 12.99, 0.18, 0.50, 460,
     "Tetley Orange Pekoe Tea Bags 216 Count",
     "Tetley Orange Pekoe Tea Bags 216 Count",
     "Tetley Orange Pekoe Tea is a classic full-bodied black tea made from carefully selected "
     "tea leaves for a consistently rich, satisfying brew. Each bag produces a robust cup "
     "with a natural deep amber colour. This 216-count value pack ensures you always have "
     "your favourite everyday tea on hand. Enjoy with milk, sugar, or plain.",
     "Tetley orange pekoe tea bags"),

    (243, 'GRO-BIGL-GRTEA-025', 9.99, 0.18, 0.50, 380,
     "Bigelow Classic Green Tea Bags 40 Count",
     "Bigelow Classic Green Tea 40 Count",
     "Bigelow Classic Green Tea is a delicately smooth tea made from quality green tea leaves "
     "that deliver a clean, light flavour with every cup. Rich in natural antioxidants, it's "
     "a refreshing choice hot or iced. Each individually wrapped bag maintains peak freshness "
     "and aroma. This 40-count box is non-GMO verified and gluten-free.",
     "Bigelow green tea bags"),

    (244, 'GRO-QUAK-INST-026', 11.99, 0.18, 0.48, 510,
     "Quaker Instant Oatmeal Variety Pack, 52 Packets",
     "Quaker Instant Oatmeal Variety Pack 52 Packets",
     "Quaker Instant Oatmeal Variety Pack includes four delicious flavours — Maple & Brown "
     "Sugar, Apples & Cinnamon, Cinnamon & Spice, and Brown Sugar & Cinnamon — in 52 "
     "individually portioned packets. Ready in 90 seconds with hot water or milk, each "
     "packet provides whole grain goodness with at least 3g of fibre per serving.",
     "Quaker instant oatmeal variety pack"),

    (245, 'GRO-KNOR-CHKN-027', 7.99, 0.18, 0.50, 530,
     "Knorr Chicken Broth Mix Instant Bouillon Cubes 72 Count",
     "Knorr Chicken Broth Bouillon Cubes 72 Count",
     "Knorr Chicken Bouillon Cubes are a convenient kitchen staple for adding rich, savoury "
     "chicken flavour to soups, stews, sauces, and rice dishes. Each cube dissolves quickly "
     "in boiling water to create a flavourful broth in seconds. The 72-cube value pack "
     "provides plenty of flavour for all your cooking needs.",
     "Knorr chicken bouillon cubes"),

    (246, 'GRO-CAMP-CRMS-028', 14.99, 0.18, 0.48, 360,
     "Campbell's Cream of Mushroom Condensed Soup, 284 ml, 8-Pack",
     "Campbells Cream of Mushroom Soup 284ml 8-Pack",
     "Campbell's Cream of Mushroom Condensed Soup is a versatile kitchen essential made "
     "with real mushrooms and no artificial colours or flavours. Use it as a creamy base "
     "for casseroles, pasta dishes, and sauces, or enjoy it as a rich, comforting soup. "
     "This 8-pack value bundle ensures you always have this pantry staple on hand.",
     "Campbell's cream of mushroom soup"),

    (247, 'GRO-PREGO-TRAD-029', 16.99, 0.18, 0.48, 290,
     "Prego Traditional Italian Tomato Pasta Sauce, 1.42 L",
     "Prego Traditional Italian Pasta Sauce 1.42L",
     "Prego Traditional Italian Pasta Sauce is a classic tomato sauce made with vine-ripened "
     "tomatoes, olive oil, and a blend of Italian herbs and spices. The smooth, rich texture "
     "coats pasta perfectly and adds homemade flavour to any dish in minutes. The convenient "
     "1.42L jar provides generous servings for family meals.",
     "Prego pasta sauce traditional"),

    (248, 'GRO-KRAFT-MAC-030', 19.99, 0.18, 0.48, 420,
     "Kraft Dinner Original Mac & Cheese, 12 Pack (225g Each)",
     "Kraft Dinner Original Macaroni Cheese 12 Pack",
     "Kraft Dinner Original Macaroni & Cheese is Canada's favourite mac and cheese, made "
     "with enriched macaroni pasta and Kraft's signature cheese sauce powder. Ready in just "
     "7 minutes on the stovetop, each 225g box serves 2-3 people. This 12-pack value bundle "
     "is a pantry staple for quick weeknight meals the whole family loves.",
     "Kraft Dinner mac and cheese 12 pack"),

    (249, 'GRO-JIF-PEANB-031', 13.99, 0.18, 0.48, 350,
     "Jif Creamy Peanut Butter, 1.36 kg",
     "Jif Creamy Peanut Butter 1.36 kg",
     "Jif Creamy Peanut Butter is made from quality roasted peanuts and has more peanut "
     "flavour than the leading brand. The smooth, creamy texture spreads easily on bread, "
     "crackers, and celery sticks. This large 1.36 kg jar provides excellent value for "
     "families and contains no artificial preservatives, colours, or sweeteners.",
     "Jif creamy peanut butter large"),

    (250, 'GRO-NUTEL-HAZE-032', 14.99, 0.18, 0.45, 380,
     "Nutella Hazelnut Chocolate Spread, 1 kg",
     "Nutella Hazelnut Chocolate Spread 1kg",
     "Nutella is a creamy blend of high-quality roasted hazelnuts, cocoa, and skim milk that "
     "delivers a unique taste experience. Perfect as a spread on toast, waffles, pancakes, "
     "and crepes, or used as an ingredient in dessert recipes. The 1 kg jar is the perfect "
     "size for families who love Nutella every day.",
     "Nutella hazelnut spread 1kg"),

    (251, 'GRO-CLIF-BARV-033', 29.99, 0.18, 0.45, 275,
     "Clif Bar Energy Bar Variety Pack, 24 Count",
     "Clif Bar Energy Bars Variety Pack 24 Count",
     "Clif Bar Energy Bars are made from 70% organic ingredients with a blend of carbohydrates, "
     "plant protein, and fibre to fuel sustained energy for outdoor adventures and active "
     "lifestyles. This 24-count variety pack includes popular flavours like Chocolate Chip, "
     "Blueberry Crisp, Crunchy Peanut Butter, and White Chocolate Macadamia Nut.",
     "Clif bar energy bars variety pack"),

    (252, 'GRO-KIND-DKCH-034', 27.99, 0.18, 0.45, 260,
     "KIND Dark Chocolate Nuts & Sea Salt Bars, 12 Count",
     "KIND Dark Chocolate Nuts Sea Salt Bars 12 Count",
     "KIND Dark Chocolate Nuts & Sea Salt bars are made with whole almonds, peanuts, and "
     "peanuts covered in rich dark chocolate and finished with a touch of sea salt. Each "
     "bar delivers 6g of protein and 5g of fibre with no artificial flavours, colours, or "
     "preservatives. Non-GMO Project Verified, gluten-free, and a low-glycaemic snack choice.",
     "KIND dark chocolate nuts sea salt bars"),

    (253, 'GRO-PLAN-MXNT-035', 19.99, 0.18, 0.45, 290,
     "Planters Mixed Nuts with Peanuts, Lightly Salted, 1 kg",
     "Planters Mixed Nuts Lightly Salted 1kg",
     "Planters Mixed Nuts with Peanuts contains a classic blend of cashews, almonds, "
     "hazelnuts, and pecans alongside peanuts, lightly salted for a satisfying crunch. "
     "A good source of protein and healthy fats, this 1 kg resealable canister is great "
     "for snacking, entertaining, and adding to trail mix.",
     "Planters mixed nuts lightly salted"),

    (254, 'GRO-BOBR-OATS-036', 12.99, 0.18, 0.48, 310,
     "Bob's Red Mill Whole Grain Rolled Oats, 2.27 kg",
     "Bobs Red Mill Whole Grain Rolled Oats 2.27kg",
     "Bob's Red Mill Whole Grain Rolled Oats are made from whole grain oats that are "
     "steam-treated and flaked to create a nutritious base for oatmeal, granola, cookies, "
     "and baked goods. Non-GMO Project Verified, this 2.27 kg bag provides 100% whole "
     "grain nutrition with 4g of fibre per serving. Certified gluten-free.",
     "Bob's Red Mill rolled oats"),

    (255, 'GRO-SMAR-CHDR-037', 7.99, 0.18, 0.50, 480,
     "Smartfood White Cheddar Flavoured Popcorn, 500 g",
     "Smartfood White Cheddar Popcorn 500g",
     "Smartfood White Cheddar Popcorn is air-popped popcorn coated in real white cheddar "
     "cheese for an irresistibly light, cheesy crunch. Made with no artificial colours or "
     "flavours, it delivers a delicious snack that's lower in calories than regular chips. "
     "This large 500g party size bag is perfect for movie nights and sharing.",
     "Smartfood white cheddar popcorn"),

    (256, 'GRO-POPCH-ORIG-038', 6.99, 0.18, 0.50, 450,
     "Popchips Original Sea Salt Potato Chips, 142 g",
     "Popchips Original Sea Salt Potato Chips 142g",
     "Popchips are never fried and never baked — they're popped using heat and pressure to "
     "create a light, crispy chip with all the flavour and half the fat of regular potato "
     "chips. Made from real potatoes with no artificial colours, flavours, or preservatives, "
     "the Sea Salt flavour is a satisfying classic snack for guilt-free munching.",
     "Popchips sea salt potato chips"),

    (257, 'GRO-TRSC-ORIG-039', 8.99, 0.18, 0.48, 410,
     "Triscuit Original Woven Wheat Crackers, 624 g (2-Pack)",
     "Triscuit Original Woven Wheat Crackers 624g 2-Pack",
     "Triscuit Original crackers are made from just three simple ingredients — whole grain "
     "wheat, canola oil, and sea salt — woven and baked for an unmistakable crunch. Each "
     "serving provides 3g of fibre from 100% whole grain wheat. This 2-pack provides "
     "excellent value for cheese boards, dips, soups, and everyday snacking.",
     "Triscuit original crackers"),

    (258, 'GRO-PRES-SALTN-040', 9.99, 0.18, 0.50, 370,
     "Christie Premium Plus Crackers, 2 kg",
     "Christie Premium Plus Saltine Crackers 2kg",
     "Christie Premium Plus Crackers are a classic Canadian pantry staple with a light, "
     "crispy texture and a delicate hint of salt. Made with enriched wheat flour, these "
     "versatile crackers are perfect for pairing with soups, salads, dips, and cheese. "
     "The 2 kg value size is ideal for families and entertaining.",
     "Christie Premium Plus crackers"),

    (259, 'GRO-LINDT-EXCL-041', 16.99, 0.20, 0.44, 295,
     "Lindt Excellence 70% Cocoa Dark Chocolate Bar, 12 x 100g",
     "Lindt Excellence 70% Dark Chocolate Bars 12 Pack",
     "Lindt Excellence 70% Cocoa Dark Chocolate is crafted by Lindt's master chocolatiers "
     "from premium cocoa beans for an intensely rich chocolate experience with complex "
     "flavour notes and a smooth, melt-in-your-mouth texture. Each 100g bar is perfect "
     "for enjoying on its own or in baking. This 12-bar pack provides exceptional value.",
     "Lindt dark chocolate 70% cocoa bars"),

    (260, 'GRO-GHOS-PEPP-042', 11.99, 0.18, 0.50, 320,
     "Ghirardelli Peppermint Bark Premium Baking Chips, 326 g",
     "Ghirardelli Peppermint Bark Premium Baking Chips 326g",
     "Ghirardelli Peppermint Bark Baking Chips combine white chocolate with refreshing "
     "peppermint flavour in a convenient baking chip form. Perfect for cookies, brownies, "
     "bark, and holiday confections, they melt smoothly and deliver premium Ghirardelli "
     "quality in every bite. Made with no artificial flavours.",
     "Ghirardelli baking chips chocolate"),

    (261, 'GRO-SRIRA-ORIG-043', 8.99, 0.18, 0.50, 400,
     "Huy Fong Sriracha Hot Chili Sauce, 793 g",
     "Huy Fong Sriracha Hot Chili Sauce 793g",
     "Huy Fong Sriracha Hot Chili Sauce is the world's favourite hot sauce made from sun-ripened "
     "jalapeño chili peppers blended with garlic, sugar, and distilled vinegar for a bright, "
     "balanced heat. Versatile enough for eggs, pizza, burgers, noodles, and anything that "
     "needs a kick. This large 793g bottle is a must-have pantry condiment.",
     "Huy Fong sriracha hot sauce"),

    (262, 'GRO-LEES-KOSH-044', 9.49, 0.18, 0.50, 360,
     "Lee Kum Kee Premium Oyster Sauce, 907 g",
     "Lee Kum Kee Premium Oyster Sauce 907g",
     "Lee Kum Kee Premium Oyster Sauce is made from fresh oyster extracts using a traditional "
     "recipe for a rich, thick sauce with a complex sweet-savoury balance. The iconic gold "
     "label brand is the #1 oyster sauce used by professional Chinese chefs worldwide. "
     "Ideal for stir-fries, marinades, braises, and noodle dishes.",
     "Lee Kum Kee oyster sauce"),

    (263, 'GRO-RICE-THIN-045', 6.99, 0.18, 0.50, 440,
     "Quaker Rice Cakes Lightly Salted, 12-Pack Multipack",
     "Quaker Rice Cakes Lightly Salted 12-Pack",
     "Quaker Lightly Salted Rice Cakes are a light, crispy snack made from whole grain brown "
     "rice with just a hint of salt. With only 35 calories per cake, they make a satisfying "
     "low-calorie snack on their own or topped with hummus, avocado, or peanut butter. "
     "Gluten-free and made with no artificial colours or flavours.",
     "Quaker rice cakes lightly salted"),

    (264, 'GRO-OREO-ORIG-046', 13.99, 0.18, 0.48, 490,
     "OREO Original Chocolate Sandwich Cookies, Family Size 992g",
     "OREO Original Chocolate Sandwich Cookies Family Size 992g",
     "OREO Original Sandwich Cookies are America's (and Canada's) favourite cookie — two "
     "chocolate wafers sandwiching a sweet creme filling made for twisting, licking, and "
     "dunking. This family-size 992g pack is perfect for sharing, baking, and making "
     "milkshakes and desserts. Made with no artificial flavours.",
     "Oreo original cookies family size"),

    (265, 'GRO-CHIPS-AHOY-047', 11.99, 0.18, 0.48, 460,
     "Chips Ahoy! Original Chocolate Chip Cookies, 650g (2-Pack)",
     "Chips Ahoy Original Chocolate Chip Cookies 650g 2-Pack",
     "Chips Ahoy! Original Chocolate Chip Cookies are crispy, crunchy cookies packed full of "
     "real chocolate chips in every bite. A beloved Canadian snack since 1963, they're "
     "perfect for lunchboxes, after-school snacks, and baking into pie crusts and desserts. "
     "This 2-pack provides excellent value for cookie lovers.",
     "Chips Ahoy chocolate chip cookies"),

    (266, 'GRO-GOLD-FISH-048', 9.99, 0.18, 0.50, 430,
     "Goldfish Cheddar Baked Snack Crackers, 624 g",
     "Goldfish Cheddar Baked Snack Crackers 624g",
     "Goldfish Baked Snack Crackers are made with real cheddar cheese and baked — never "
     "fried — for a delicious snack with no artificial flavours or preservatives. The iconic "
     "fish-shaped crackers are a beloved snack for kids and adults alike. This large 624g "
     "bag contains 40% of the daily value of calcium per serving.",
     "Goldfish cheddar crackers large bag"),

    (267, 'GRO-NATUR-HONY-049', 14.99, 0.18, 0.48, 320,
     "Natural Honey Pure and Natural Clover Honey, 1 kg",
     "Natural Honey Pure Clover Honey 1kg",
     "Pure Canadian Clover Honey is harvested from Canadian clover fields and bottled "
     "without additives or artificial ingredients. Light and mild with a sweet, delicate "
     "flavour, it's perfect for sweetening tea, drizzling over yogurt and oatmeal, baking, "
     "and spreading on toast. This 1 kg squeeze bottle provides convenient everyday use.",
     "pure clover honey canada 1kg"),

    (268, 'GRO-PCORG-QUIN-050', 11.99, 0.18, 0.48, 270,
     "PC Organics Quinoa, 850 g",
     "PC Organics Quinoa 850g",
     "PC Organics Quinoa is a certified organic, gluten-free whole grain superfood that "
     "provides complete protein with all nine essential amino acids. Quick-cooking in just "
     "15 minutes, it's a versatile base for grain bowls, salads, soups, and side dishes. "
     "Pre-washed for convenience, this 850g resealable bag offers excellent everyday value.",
     "PC Organics quinoa organic"),

    (269, 'GRO-PCORG-CHIA-051', 9.99, 0.18, 0.48, 300,
     "PC Organics Black Chia Seeds, 500 g",
     "PC Organics Black Chia Seeds 500g",
     "PC Organics Black Chia Seeds are certified organic, non-GMO superseeds rich in "
     "omega-3 fatty acids, fibre, calcium, and protein. Add them to smoothies, yogurt, "
     "oatmeal, and baked goods for an easy nutrition boost, or make chia pudding for a "
     "healthy make-ahead breakfast. Gluten-free and vegan.",
     "PC Organics chia seeds organic"),

    (270, 'GRO-ANCNC-MAPSY-052', 19.99, 0.18, 0.45, 260,
     "PC 100% Pure Canadian Maple Syrup, Grade A Dark, 1 L",
     "PC 100% Pure Canadian Maple Syrup Grade A Dark 1L",
     "PC 100% Pure Canadian Maple Syrup is sourced directly from Canadian maple trees and "
     "bottled with no added ingredients. Grade A Dark has a robust maple flavour perfect "
     "for pancakes, waffles, French toast, and as a natural sweetener in baking and cooking. "
     "This 1L bottle provides plenty of pure Canadian goodness for the whole family.",
     "pure Canadian maple syrup grade A dark"),
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

def sanitize_folder(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip().rstrip(' ,.')
    return name[:100]

def fetch_page(session, url, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (503, 429):
                wait = 15 + attempt * 10
                print(f"  HTTP {r.status_code} – waiting {wait}s")
                time.sleep(wait)
            else:
                print(f"  HTTP {r.status_code}")
        except Exception as e:
            print(f"  Request error: {e}")
        time.sleep(5)
    return None

def search_amazon(session, query):
    from bs4 import BeautifulSoup
    html = fetch_page(session, f"https://www.amazon.ca/s?k={query.replace(' ', '+')}")
    if not html:
        return []
    soup = BeautifulSoup(html, 'lxml')
    results = []
    for card in soup.select('[data-component-type="s-search-result"]'):
        asin = card.get('data-asin', '')
        if not asin:
            continue
        h2_link   = card.select_one('h2 a')
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
        if len(title) >= 8:
            results.append({'title': title, 'url': product_url})
    return results

def get_product_images(session, product_url):
    from bs4 import BeautifulSoup
    html = fetch_page(session, product_url)
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
            try:
                image_urls.extend(list(json.loads(img.get('data-a-dynamic-image', '{}')).keys()))
            except Exception:
                pass
    if not image_urls:
        main = soup.select_one('#landingImage, #imgBlkFront')
        if main:
            src = main.get('data-old-hires') or main.get('src', '')
            if src:
                image_urls.append(src)
        for thumb in soup.select('#altImages img'):
            src = re.sub(r'\._[A-Z0-9_,]+_\.', '._AC_SL1500_.', thumb.get('src', ''))
            if src.startswith('https://') and 'sprite' not in src:
                image_urls.append(src)
    seen, clean = set(), []
    for u in image_urls:
        u = u.strip()
        if u and u not in seen and 'sprite' not in u and u.startswith('http'):
            seen.add(u)
            clean.append(u)
    return clean[:IMAGES_PER]

def download_image(session, url, dest):
    try:
        r = session.get(url, timeout=25, stream=True)
        if r.status_code == 200 and len(r.content) > 2000:
            with open(dest, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"    [dl error] {e}")
    return False


# ── cPanel helpers ─────────────────────────────────────────────────────────────

CPANEL_HEADERS = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}
CPANEL_API_URL = f"{CPANEL_HOST}/json-api/cpanel"

def cpanel_api(module, func, data=None, files=None):
    params = {"cpanel_jsonapi_version": "2", "cpanel_jsonapi_module": module,
              "cpanel_jsonapi_func": func}
    try:
        r = requests.post(CPANEL_API_URL, headers=CPANEL_HEADERS, params=params,
                          data=data or {}, files=files, verify=False, timeout=60)
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}

def cpanel_ok(res):
    return res.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1

def mkdir_remote(parent, name):
    """ALWAYS pass unencoded name (spaces) — Apache decodes %20 → space on serve."""
    res = cpanel_api("Fileman", "mkdir", data={"path": parent, "name": name})
    if cpanel_ok(res):
        return True
    err = str(res.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"    [mkdir FAIL] {name}: {err}")
    return False

def list_remote_files(remote_dir):
    res = cpanel_api("Fileman", "listfiles", data={"dir": remote_dir, "include_mime": 0})
    entries = res.get("cpanelresult", {}).get("data", [])
    out = {}
    for e in entries:
        if e.get("type") == "file":
            try:
                out[e["file"]] = int(e.get("size") or 0)
            except Exception:
                out[e["file"]] = 0
    return out

def upload_file_cpanel(local_path, remote_dir):
    filename = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        res = cpanel_api("Fileman", "uploadfiles",
                         data={"dir": remote_dir, "overwrite": 1},
                         files={"file-1": (filename, f, "application/octet-stream")})
    cr = res.get("cpanelresult", {})
    data = cr.get("data", [{}])
    uploads = data[0].get("uploads", []) if data else []
    if uploads and uploads[0].get("status") == 1:
        return True
    if data and data[0].get("succeeded", 0) == 1:
        return True
    reason = uploads[0].get("reason", "") if uploads else ""
    if "already exists" in reason.lower():
        return True
    err = cr.get("error") or reason or str(res)
    print(f"    [upload FAIL] {filename}: {err}")
    return False


# ── SQL generation ─────────────────────────────────────────────────────────────

def generate_sql():
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                             user=DB_USER, password=DB_PASS)
    cur  = conn.cursor()

    def esc(v):
        if v is None:
            return 'NULL'
        return "'" + str(v).replace("'", "''") + "'"

    lines = []
    def w(s=''):
        lines.append(s)

    w('-- ============================================================')
    w('-- INSERT 32 best-selling Grocery products + pricing + images')
    w(f'-- Generated: {NOW[:10]}')
    w('-- Products  : 32 rows  (product_number 239-270)')
    w('-- Pricing   : 96 rows  (Retail + Promo + Wholesale per product)')
    w('-- Images    : 160 rows (5 images per product)')
    w('-- Category  : Grocery  (fea01756-1ba1-4b38-841f-c6a2b86bb2a6)')
    w('-- Currency  : CAD')
    w('-- ============================================================')
    w()

    # SECTION 1 ── products
    cur.execute("""
        SELECT p.product_id, p.product_number, p.product_name, p.sku, p.description,
               p.category_id, p.currency_code, p.stock_quantity,
               p.is_active, p.is_synthetic, p.created_at, p.updated_at
        FROM products p
        JOIN category c ON p.category_id = c.category_id
        WHERE c.category_name = 'Grocery' AND p.product_number >= 239
        ORDER BY p.product_number
    """)
    products = cur.fetchall()
    w('-- ============================================================')
    w(f'-- SECTION 1: products ({len(products)} rows)')
    w('-- ============================================================')
    w()
    for row in products:
        pid, num, name, sku, desc, cat, cc, stock, ia, isy, cr, up = row
        ia_s  = 'TRUE' if ia  else 'FALSE'
        isy_s = 'TRUE' if isy else 'FALSE'
        cr_s  = cr.strftime('%Y-%m-%d %H:%M:%S+00')
        up_s  = up.strftime('%Y-%m-%d %H:%M:%S+00')
        w(f'-- [{num}] {name[:72]}')
        w('INSERT INTO products')
        w('  (product_id, product_number, product_name, sku, description,')
        w('   category_id, currency_code, stock_quantity, is_active, is_synthetic, created_at, updated_at)')
        w('VALUES')
        w(f'  ({esc(str(pid))}, {num}, {esc(name)}, {esc(sku)}, {esc(desc)},')
        w(f'   {esc(str(cat))}, {esc(cc)}, {stock}, {ia_s}, {isy_s}, {esc(cr_s)}, {esc(up_s)})')
        w('ON CONFLICT (sku) DO UPDATE SET')
        w('  product_name   = EXCLUDED.product_name,')
        w('  description    = EXCLUDED.description,')
        w('  stock_quantity = EXCLUDED.stock_quantity,')
        w('  updated_at     = EXCLUDED.updated_at;')
        w()

    # SECTION 2 ── product_pricing
    cur.execute("""
        SELECT pp.product_pricing_id, pp.product_id, p.sku, p.product_number,
               pp.price_type, pp.price_value, pp.currency_code,
               pp.is_synthetic, pp.created_at, pp.updated_at
        FROM product_pricing pp
        JOIN products p ON pp.product_id = p.product_id
        WHERE p.product_number BETWEEN 239 AND 270
        ORDER BY p.product_number,
                 CASE pp.price_type WHEN 'Retail' THEN 1 WHEN 'Promo' THEN 2 ELSE 3 END
    """)
    pricing = cur.fetchall()
    w(); w('-- ============================================================')
    w(f'-- SECTION 2: product_pricing ({len(pricing)} rows)')
    w('-- ============================================================'); w()
    w('DELETE FROM product_pricing')
    w('WHERE product_id IN (')
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 239 AND 270')
    w(');'); w()
    for row in pricing:
        ppid, pid, sku, num, ptype, pval, cc, isy, cr, up = row
        isy_s = 'TRUE' if isy else 'FALSE'
        cr_s  = cr.strftime('%Y-%m-%d %H:%M:%S+00')
        up_s  = up.strftime('%Y-%m-%d %H:%M:%S+00')
        w(f'-- [{num}] {sku}  {ptype}: ${pval}')
        w('INSERT INTO product_pricing')
        w('  (product_pricing_id, product_id, price_type, price_value, currency_code,')
        w('   is_synthetic, created_at, updated_at)')
        w('VALUES')
        w(f'  ({esc(str(ppid))}, {esc(str(pid))}, {esc(ptype)}, {pval}, {esc(cc)},')
        w(f'   {isy_s}, {esc(cr_s)}, {esc(up_s)});'); w()

    # SECTION 3 ── product_image
    cur.execute("""
        SELECT pi.product_image_id, pi.product_id, p.sku, p.product_number,
               pi.image_url, pi.sort_order, pi.alt_text, pi.created_at
        FROM product_image pi
        JOIN products p ON pi.product_id = p.product_id
        WHERE p.product_number BETWEEN 239 AND 270
        ORDER BY p.product_number, pi.sort_order
    """)
    images = cur.fetchall()
    w(); w('-- ============================================================')
    w(f'-- SECTION 3: product_image ({len(images)} rows)')
    w('-- ============================================================'); w()
    w('DELETE FROM product_image')
    w('WHERE product_id IN (')
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 239 AND 270')
    w(');'); w()
    for row in images:
        piid, pid, sku, num, url, sort, alt, cr = row
        cr_s = cr.strftime('%Y-%m-%d %H:%M:%S+00')
        w(f'-- [{num}] {sku}  sort={sort}')
        w('INSERT INTO product_image')
        w('  (product_image_id, product_id, image_url, sort_order, alt_text, created_at)')
        w('VALUES')
        w(f'  ({esc(str(piid))}, {esc(str(pid))}, {esc(url)}, {sort}, {esc(alt)}, {esc(cr_s)});')
        w()

    conn.close()
    with open(SQL_OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"\nSQL saved → {SQL_OUT}")
    print(f"  Products: {len(products)}  Pricing: {len(pricing)}  Images: {len(images)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session = make_session()
    print("Warming up Amazon.ca session...")
    try:
        session.get("https://www.amazon.ca", timeout=15)
        time.sleep(2)
    except Exception as e:
        print(f"  Warning: {e}")

    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                             user=DB_USER, password=DB_PASS)
    conn.autocommit = False
    cur = conn.cursor()

    local_cat_dir  = os.path.join(IMAGE_BASE, "Grocery")
    remote_cat_dir = f"{REMOTE_BASE}/Grocery"
    os.makedirs(local_cat_dir, exist_ok=True)

    succeeded = []
    failed    = []

    for (num, sku, retail, ws_pct, promo_ratio, stock,
         name, folder_name, desc, search_query) in PRODUCTS:

        print(f"\n{'='*70}")
        print(f"[{num}] {name[:70]}")

        folder     = sanitize_folder(folder_name)
        local_dir  = os.path.join(local_cat_dir, folder)
        remote_dir = f"{remote_cat_dir}/{folder}"   # unencoded — spaces intact
        folder_enc = quote(folder, safe='')          # for DB URLs only
        os.makedirs(local_dir, exist_ok=True)

        # ── Step 1: Download images ──────────────────────────────────────────
        existing_imgs = sorted([
            f for f in os.listdir(local_dir)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
        ])
        if len(existing_imgs) >= IMAGES_PER:
            print(f"  [SKIP download] Already have {len(existing_imgs)} images")
        else:
            sleep()
            print(f"  Searching Amazon.ca: {search_query}")
            candidates = search_amazon(session, search_query)
            print(f"  Found {len(candidates)} candidates")
            session.headers['User-Agent'] = random.choice(USER_AGENTS)

            downloaded = len(existing_imgs)
            for cand in candidates[:4]:
                if downloaded >= IMAGES_PER:
                    break
                print(f"  Trying: {cand['title'][:60]}")
                sleep()
                img_urls = get_product_images(session, cand['url'])
                print(f"  Found {len(img_urls)} images")
                for img_url in img_urls:
                    if downloaded >= IMAGES_PER:
                        break
                    ext = '.jpg'
                    m = re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', img_url, re.I)
                    if m:
                        ext = '.' + m.group(1).lower()
                    fname = os.path.join(local_dir, f"image_{downloaded+1}{ext}")
                    if download_image(session, img_url, fname):
                        downloaded += 1
                        print(f"    Downloaded {downloaded}/{IMAGES_PER}")
                if downloaded >= IMAGES_PER:
                    break

            existing_imgs = sorted([
                f for f in os.listdir(local_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ])
            print(f"  Total images: {len(existing_imgs)}")

        # ── Step 2: Upload to cPanel (unencoded remote dir) ──────────────────
        print(f"  Uploading to cPanel: {folder[:58]}")
        mkdir_remote(remote_cat_dir, folder)   # ← spaces, not %20

        existing_remote = list_remote_files(remote_dir)
        uploaded = 0
        for img_file in existing_imgs[:IMAGES_PER]:
            local_path  = os.path.join(local_dir, img_file)
            remote_size = existing_remote.get(img_file, -1)
            if remote_size > 0:
                print(f"    [SKIP] {img_file}")
                uploaded += 1
                continue
            ok = upload_file_cpanel(local_path, remote_dir)
            print(f"    [{'OK' if ok else 'FAIL'}] {img_file}")
            if ok:
                uploaded += 1
                time.sleep(0.3)
        print(f"  Uploaded {uploaded}/{len(existing_imgs[:IMAGES_PER])}")

        # ── Step 3: Database insert ──────────────────────────────────────────
        ws    = round(retail * (1.0 - ws_pct), 2)
        promo = round(retail - (retail - ws) * promo_ratio, 2)
        product_id = str(uuid.uuid4())

        try:
            cur.execute('''
                INSERT INTO products
                  (product_id, product_number, product_name, sku, description,
                   category_id, currency_code, stock_quantity, is_active, is_synthetic,
                   created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'CAD',%s,TRUE,FALSE,%s,%s)
                ON CONFLICT (sku) DO UPDATE SET
                  product_name   = EXCLUDED.product_name,
                  description    = EXCLUDED.description,
                  stock_quantity = EXCLUDED.stock_quantity,
                  updated_at     = EXCLUDED.updated_at
                RETURNING product_id
            ''', (product_id, num, name, sku, desc,
                  GROCERY_CAT_ID, stock, NOW, NOW))
            actual_pid = cur.fetchone()[0]

            cur.execute('DELETE FROM product_image   WHERE product_id = %s', (actual_pid,))
            cur.execute('DELETE FROM product_pricing WHERE product_id = %s', (actual_pid,))

            img_files = sorted([
                f for f in os.listdir(local_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ])[:IMAGES_PER]

            for sort_order, img_file in enumerate(img_files, 1):
                img_url = f"https://agentorc.ca/image/Grocery/{folder_enc}/{img_file}"
                cur.execute('''
                    INSERT INTO product_image
                      (product_image_id, product_id, image_url, sort_order, alt_text, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                ''', (str(uuid.uuid4()), actual_pid, img_url, sort_order,
                      f"{name[:80]} - image {sort_order}", NOW))

            for ptype, pval in [('Retail', retail), ('Promo', promo), ('Wholesale', ws)]:
                cur.execute('''
                    INSERT INTO product_pricing
                      (product_pricing_id, product_id, price_type, price_value,
                       currency_code, is_synthetic, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,'CAD',FALSE,%s,%s)
                ''', (str(uuid.uuid4()), actual_pid, ptype, pval, NOW, NOW))

            conn.commit()
            print(f"  DB OK  retail=${retail:.2f}  promo=${promo:.2f}  ws=${ws:.2f}  imgs={len(img_files)}")
            succeeded.append(sku)

        except Exception as e:
            conn.rollback()
            print(f"  DB ERROR: {e}")
            import traceback; traceback.print_exc()
            failed.append(sku)

        session.headers['User-Agent'] = random.choice(USER_AGENTS)

    conn.close()

    # ── Generate SQL ──────────────────────────────────────────────────────────
    if succeeded:
        generate_sql()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"DONE.  Succeeded: {len(succeeded)}/{len(PRODUCTS)}")
    if failed:
        print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
