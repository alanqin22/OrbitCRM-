"""
Add 35 best-selling Apparel products:
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally  → image/Apparel/{Folder Name}/image_N.jpg
  3. Uploads to agentorc.ca using UNENCODED folder names (spaces, not %20)
     so Apache can resolve /image/Apparel/Folder%20Name/image_1.jpg correctly
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)
  5. Generates sql/insert_35_apparel.sql

Run from project root:
    python scripts/add_35_apparel.py
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os, re, json, time, random, uuid, requests
from urllib.parse import quote
from datetime import datetime, timezone
import psycopg2
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────
IMAGE_BASE   = r"D:\a\crm_agent\image"
SQL_OUT      = r"D:\a\crm_agent\sql\insert_35_apparel.sql"
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

APPAREL_CAT_ID = "7632ef73-7a4a-4320-b5d8-a2bb72bd8c03"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 35 Best-selling Apparel products ─────────────────────────────────────────
# (product_number, sku, retail_cad, ws_pct, promo_ratio, stock,
#  full_product_name, folder_name, description, amazon_search_query)
# ws_pct: wholesale = retail * (1 - ws_pct)
# promo_ratio: promo = retail - (retail-ws)*promo_ratio  [0-1]
PRODUCTS = [
    (204,'APP-NIKE-DRIFT-016', 45.00, 0.20, 0.45, 320,
     "Nike Men's Dri-FIT Legend Short-Sleeve Training T-Shirt",
     "Nike Mens Dri-FIT Legend T-Shirt",
     "Nike Men's Dri-FIT Legend T-Shirt features sweat-wicking Dri-FIT fabric that moves "
     "moisture away from skin to help keep you dry and comfortable during intense workouts. "
     "The lightweight, soft fabric offers a standard fit with a crew neck and short sleeves, "
     "making it ideal for training, running, or everyday casual wear.",
     "Nike men dri-fit training t-shirt"),

    (205,'APP-LEVI-511S-017', 89.99, 0.20, 0.42, 240,
     "Levi's Men's 511 Slim Fit Jeans",
     "Levis Mens 511 Slim Fit Jeans",
     "Levi's 511 Slim Fit Jeans are cut close to the thigh with a slim leg opening that sits "
     "below the waist. Made from durable stretch denim that moves with you, these versatile "
     "jeans are great for work, weekends, and everything in between. The classic five-pocket "
     "styling works with everything from sneakers to dress shoes.",
     "Levi's 511 slim jeans men"),

    (206,'APP-TNFC-TECO-018', 299.99, 0.22, 0.40, 95,
     "The North Face Women's Thermoball Eco Jacket",
     "The North Face Womens Thermoball Eco Jacket",
     "The North Face Thermoball Eco Jacket uses PrimaLoft ThermoBall Eco insulation made "
     "from 100% recycled content to keep you warm even when wet. The packable design stuffs "
     "into its own pocket, and the zip-up construction features a hem cinch-cord, zip hand "
     "pockets, and an internal chest pocket for secure storage on the go.",
     "North Face Thermoball jacket women"),

    (207,'APP-COLU-ARCF-019', 119.99, 0.20, 0.45, 185,
     "Columbia Men's Steens Mountain Full Zip 2.0 Soft Fleece Jacket",
     "Columbia Mens Steens Mountain Full Zip Fleece",
     "Columbia Men's Steens Mountain Full-Zip 2.0 Fleece Jacket is crafted from 100% polyester "
     "MTR filament fleece for exceptional warmth-to-weight ratio. Features include two zippered "
     "hand pockets, a chin guard for comfort, and a modern fit that works layered under a shell "
     "or worn on its own for cool-weather activities.",
     "Columbia men fleece jacket full zip"),

    (208,'APP-CHAM-MENS-020', 59.99, 0.18, 0.48, 265,
     "Champion Men's Powerblend Fleece Pullover Hoodie",
     "Champion Mens Powerblend Fleece Pullover Hoodie",
     "Champion's Powerblend Fleece is a cotton-rich fabric with reduced pilling that gets "
     "softer with every wash. This pullover hoodie features a double-lined hood with "
     "a drawstring, a front pouch pocket, and ribbed cuffs and hem. The embroidered 'C' "
     "logo on the left sleeve adds classic Champion style.",
     "Champion men powerblend hoodie"),

    (209,'APP-GILDAN-HVY-021', 34.99, 0.18, 0.50, 480,
     "Gildan Men's Heavy Cotton T-Shirt, Multipack 6-Pack",
     "Gildan Mens Heavy Cotton T-Shirts 6-Pack",
     "Gildan Men's Heavy Cotton T-Shirts are made from 100% preshrunk ring-spun cotton "
     "for a smooth, comfortable feel that lasts. The classic crew-neck cut features taped "
     "neck and shoulders for durability, with double-needle stitched sleeves and bottom "
     "hem. Available in a convenient 6-pack of assorted or solid colours.",
     "Gildan men heavy cotton t-shirt 6 pack"),

    (210,'APP-ADID-STRA-022', 49.99, 0.20, 0.45, 310,
     "Adidas Women's Essentials Linear Slim Leggings",
     "Adidas Womens Essentials Linear Leggings",
     "Adidas Essentials Linear Leggings are made from soft interlock fabric that feels "
     "comfortable against the skin for all-day wear. A high waist and wide waistband provide "
     "a secure fit, while the slim cut and iconic Adidas 3-Stripes side detail add sporty "
     "style. Made from recycled materials as part of Adidas' commitment to sustainability.",
     "Adidas women essentials leggings"),

    (211,'APP-CARH-MIDW-023', 79.99, 0.20, 0.42, 195,
     "Carhartt Men's Midweight Crewneck Sweatshirt",
     "Carhartt Mens Midweight Crewneck Sweatshirt",
     "Carhartt's Midweight Crewneck Sweatshirt is made from 10-ounce, 50/50 cotton/polyester "
     "fleece for durable warmth on the job or off. Features include a rib-knit collar, cuffs, "
     "and waistband for a comfortable fit, with left-chest and front pocket for convenient "
     "storage. The rugged Carhartt construction is built to last through tough conditions.",
     "Carhartt men crewneck sweatshirt"),

    (212,'APP-NIKEW-RUN-024', 79.99, 0.20, 0.44, 225,
     "Nike Women's One Dri-FIT Tights High-Waisted Leggings",
     "Nike Womens One Dri-FIT High Waist Leggings",
     "Nike One Dri-FIT Tights feature high-waisted design that holds everything in place "
     "during any workout. Dri-FIT technology wicks sweat away while the 7/8-length cut "
     "and compressive fit support your movement. A back waistband pocket keeps a phone "
     "secure, and the wide waistband allows customizable coverage.",
     "Nike women one leggings high waist"),

    (213,'APP-LEVI-711W-025', 79.99, 0.20, 0.45, 210,
     "Levi's Women's 311 Shaping Skinny Jeans",
     "Levis Womens 311 Shaping Skinny Jeans",
     "Levi's 311 Shaping Skinny Jeans are designed with a signature shaping panel in the "
     "front to smooth and shape your curves. The stretch denim hugs your body from hip to "
     "ankle while still allowing freedom of movement. Sits below the waist with a zip fly "
     "and five-pocket styling for classic versatility.",
     "Levi's women 311 skinny jeans"),

    (214,'APP-TOMH-POLO-026', 99.99, 0.20, 0.42, 175,
     "Tommy Hilfiger Men's Short-Sleeve Pique Polo Shirt",
     "Tommy Hilfiger Mens Classic Pique Polo Shirt",
     "Tommy Hilfiger's Classic Pique Polo is a wardrobe staple made from soft cotton pique "
     "fabric with the iconic Tommy Hilfiger flag embroidered at the chest. Features include "
     "a ribbed collar and sleeve cuffs, two-button placket, and a shirt tail hem. Machine "
     "washable and perfect for smart-casual dressing at work or on weekends.",
     "Tommy Hilfiger men polo shirt"),

    (215,'APP-UNDER-TECH-027', 39.99, 0.18, 0.50, 290,
     "Under Armour Men's HeatGear Compression Short-Sleeve T-Shirt",
     "Under Armour Mens HeatGear Compression T-Shirt",
     "Under Armour HeatGear compression T-shirt wicks sweat and dries fast to keep you cool "
     "during workouts. The 4-way stretch construction moves better in every direction, while "
     "anti-odor technology prevents the growth of odor-causing microbes. The flatlock seams "
     "reduce chafing for a second-skin fit that stays in place during intense activity.",
     "Under Armour heatgear compression shirt men"),

    (216,'APP-WRAN-ORIG-028', 54.99, 0.18, 0.48, 260,
     "Wrangler Men's Authentics Classic 5-Pocket Regular Fit Cotton Jean",
     "Wrangler Mens Authentics Classic Regular Fit Jeans",
     "Wrangler Authentics Classic 5-Pocket Jeans are made from 100% cotton denim for an "
     "authentic feel and durable performance. The regular fit sits at the natural waist and "
     "provides a straight leg with room to move. Reinforced at stress points and finished "
     "with a zip-fly and classic five-pocket design for timeless style.",
     "Wrangler men regular fit jeans"),

    (217,'APP-PATAGONIA-NP-029', 359.99, 0.22, 0.38, 72,
     "Patagonia Men's Nano Puff Hoody Jacket",
     "Patagonia Mens Nano Puff Hoody Jacket",
     "Patagonia Nano Puff Hoody uses 60-g PrimaLoft Gold Insulation Eco — made from 55% "
     "recycled content — to provide lightweight warmth that performs even when damp. The "
     "windproof and water-resistant outer fabric, hood with single-hand adjustment, and "
     "packable design make this a versatile layer for hiking, travel, and everyday use.",
     "Patagonia nano puff hoody men"),

    (218,'APP-HANES-WOMTT-030', 34.99, 0.18, 0.50, 420,
     "Hanes Women's Perfect-T Short Sleeve T-Shirt 6-Pack",
     "Hanes Womens Perfect-T Short Sleeve T-Shirts 6-Pack",
     "Hanes Perfect-T Women's T-Shirts are made from lightweight 100% cotton jersey that "
     "feels soft and comfortable for everyday wear. The flattering crew neck and relaxed "
     "fit make them easy to layer or wear alone. Comes in a convenient 6-pack and features "
     "a tagless interior for all-day comfort without irritation.",
     "Hanes women t-shirt 6 pack"),

    (219,'APP-NIKE-CLUB-031', 79.99, 0.20, 0.45, 245,
     "Nike Men's Club Fleece Pullover Hoodie",
     "Nike Mens Club Fleece Pullover Hoodie",
     "Nike Club Fleece Hoodie is made from a brushed-back fleece fabric that is soft on the "
     "inside and smooth on the outside. A standard fit, double-lined hood with adjustable "
     "drawcord, and front kangaroo pocket deliver classic comfort. The embroidered Nike "
     "Swoosh adds a clean, recognizable detail to the chest.",
     "Nike men club fleece pullover hoodie"),

    (220,'APP-CHAM-WOMS-032', 54.99, 0.18, 0.48, 230,
     "Champion Women's Heritage Fleece Pullover Hoodie",
     "Champion Womens Heritage Fleece Pullover Hoodie",
     "Champion Heritage Fleece Pullover Hoodie is crafted from a heavyweight fleece blend "
     "that softens with every wash. The classic boxy fit, front kangaroo pocket, and "
     "adjustable drawstring hood create a relaxed, comfortable silhouette. The iconic "
     "Champion script logo across the chest adds vintage varsity-inspired style.",
     "Champion women heritage fleece hoodie"),

    (221,'APP-COLU-SWBK-033', 149.99, 0.20, 0.44, 155,
     "Columbia Women's Switchback III Adjustable Waterproof Rain Jacket",
     "Columbia Womens Switchback III Waterproof Rain Jacket",
     "Columbia Switchback III is a lightweight waterproof rain jacket with an adjustable "
     "hem and cuffs for a customized fit. Omni-Tech fully seam-sealed waterproof breathable "
     "fabric keeps you dry in wet conditions, while the packable design stuffs into its own "
     "pocket for portability. A zippered chest pocket, two zippered hand pockets, and a "
     "roll-up hood complete the functional design.",
     "Columbia women rain jacket waterproof"),

    (222,'APP-DICK-874-034', 49.99, 0.18, 0.50, 300,
     "Dickies Men's Original 874 Work Pant",
     "Dickies Mens Original 874 Work Pant",
     "Dickies Original 874 Work Pants are an iconic workwear staple made from a durable "
     "65% polyester 35% cotton blend that resists wrinkles, soil, and fading. The straight "
     "leg fit sits at the natural waist with a comfortable cotton waistband and two side "
     "slash pockets, two back welt pockets, and hidden snap closures.",
     "Dickies 874 work pants men"),

    (223,'APP-ADID-TIRO-035', 54.99, 0.20, 0.45, 285,
     "Adidas Men's Tiro 23 Club Training Pants",
     "Adidas Mens Tiro 23 Training Pants",
     "Adidas Tiro 23 Club Training Pants feature moisture-absorbing AEROREADY fabric to "
     "keep you dry during high-intensity training. Side zipped pockets keep belongings "
     "secure, and the elastic waist with drawstring provides an adjustable fit. The iconic "
     "3-Stripe and Adidas badge detailing along the side seam adds classic sporty style.",
     "Adidas men tiro training pants"),

    (224,'APP-GILDAN-WMNS-036', 29.99, 0.18, 0.50, 395,
     "Gildan Women's Heavy Blend Crewneck Sweatshirt",
     "Gildan Womens Heavy Blend Crewneck Sweatshirt",
     "Gildan Women's Heavy Blend Crewneck Sweatshirt is made from 50% cotton and 50% "
     "polyester fleece that stays soft wash after wash. The fabric is pill-resistant and "
     "air-jet spun yarn reduces pilling throughout the life of the garment. Features include "
     "a double-needle stitched neckline and ribbed cuffs and waistband for durability.",
     "Gildan women heavy blend crewneck sweatshirt"),

    (225,'APP-PUMA-ESLT-037', 34.99, 0.18, 0.50, 350,
     "Puma Men's Essential Logo Short Sleeve T-Shirt",
     "Puma Mens Essential Logo T-Shirt",
     "Puma Men's Essential Logo T-Shirt is made from soft single-jersey cotton fabric with "
     "dryCELL moisture-wicking technology to keep you comfortable during workouts or casual "
     "wear. The regular fit crew neck design features a bold Puma Cat logo at the chest and "
     "is available in a variety of solid colours and sizes S through 2XL.",
     "Puma men essential t-shirt"),

    (226,'APP-CKVN-BXBR-038', 49.99, 0.20, 0.45, 280,
     "Calvin Klein Men's Cotton Stretch 5-Pack Boxer Brief",
     "Calvin Klein Mens Cotton Stretch Boxer Briefs 5-Pack",
     "Calvin Klein Men's Cotton Stretch Boxer Briefs feature a contour pouch for comfort "
     "and support, made from a soft 95% cotton 5% elastane blend that moves with your body. "
     "The 5-pack includes the iconic CK waistband logo and is available in multicolor "
     "assortments. Machine washable and designed for all-day comfort.",
     "Calvin Klein men boxer briefs 5 pack"),

    (227,'APP-LEVI-505-039', 84.99, 0.20, 0.44, 190,
     "Levi's Men's 505 Regular Fit Jeans",
     "Levis Mens 505 Regular Fit Jeans",
     "Levi's 505 Regular Fit Jeans offer a classic straight-leg cut with room through the "
     "seat and thigh for a comfortable, traditional fit. Made from authentic denim, they "
     "feature a zip fly and five-pocket construction. Versatile enough for work or casual "
     "wear, they pair easily with everything from flannel shirts to dress shirts.",
     "Levi's 505 regular fit jeans men"),

    (228,'APP-CARH-CLKB-040', 74.99, 0.20, 0.45, 165,
     "Carhartt Women's Clarksburg Pullover Sweatshirt",
     "Carhartt Womens Clarksburg Pullover Sweatshirt",
     "Carhartt Women's Clarksburg Pullover Sweatshirt is made from 10-ounce, 50/50 "
     "cotton/polyester fleece that balances warmth and breathability. Features a relaxed "
     "fit, two front patch pockets, rib-knit cuffs and waistband, and a straight hem. "
     "The midweight fleece is ideal for cool-weather layering on outdoor work or leisure.",
     "Carhartt women pullover sweatshirt"),

    (229,'APP-ADID-ULT-041', 89.99, 0.20, 0.44, 200,
     "Adidas Women's Ultraboost 22 Running Shoes",
     "Adidas Womens Ultraboost 22 Running Shoes",
     "Adidas Ultraboost 22 Women's Running Shoes feature a responsive BOOST midsole that "
     "returns energy with every stride and a Primeknit+ upper that wraps the foot for a "
     "supportive, adaptive fit. The Linear Energy Push system enhances your natural gait "
     "cycle for a smooth, efficient run on roads or treadmill.",
     "Adidas women ultraboost running shoes"),

    (230,'APP-NIKEW-AIR-042', 129.99, 0.20, 0.42, 145,
     "Nike Women's Air Max 270 Lifestyle Shoe",
     "Nike Womens Air Max 270 Shoes",
     "Nike Air Max 270 features Nike's biggest heel Air unit yet for plush cushioning in "
     "every step. The breathable mesh upper is lightweight and keeps airflow moving to your "
     "feet, while the foam midsole provides comfortable all-day wear. The bold Air Max heel "
     "window is a nod to the archive with a modern design twist.",
     "Nike women air max 270 shoes"),

    (231,'APP-RALPHL-CBLK-043', 149.99, 0.22, 0.42, 120,
     "Polo Ralph Lauren Women's Cable-Knit Cotton Sweater",
     "Polo Ralph Lauren Womens Cable Knit Sweater",
     "Polo Ralph Lauren Women's Cable-Knit Sweater is crafted from premium cotton with a "
     "classic cable-knit pattern that adds textural interest and warmth. The relaxed crew "
     "neck fit features ribbed trim at the neck, cuffs, and hem, with the iconic pony logo "
     "embroidered at the chest. A timeless wardrobe staple for smart-casual styling.",
     "Ralph Lauren women cable knit sweater"),

    (232,'APP-LACOSTE-POLO-044', 129.99, 0.22, 0.40, 130,
     "Lacoste Men's Classic Fit Short Sleeve L.12.12 Polo Shirt",
     "Lacoste Mens Classic Fit L.12.12 Polo Shirt",
     "Lacoste L.12.12 Polo Shirt is the original polo, born in 1933 when René Lacoste "
     "first wore it on the tennis court. Made from petit piqué cotton, this classic fit "
     "shirt features the iconic embroidered crocodile at the chest, a three-button placket, "
     "and a shirt tail hem for a clean, preppy look that has stood the test of time.",
     "Lacoste men polo shirt"),

    (233,'APP-CATERPILLAR-HDY-045', 99.99, 0.20, 0.45, 155,
     "Caterpillar Men's Trademark Hoodie Sweatshirt",
     "Caterpillar Mens Trademark Hoodie Sweatshirt",
     "Caterpillar Trademark Hoodie is built for hard-working comfort with a heavyweight "
     "80% cotton 20% polyester fleece construction. Features a double-lined hood, large "
     "front kangaroo pocket for tool storage, and reinforced ribbing at cuffs and waistband. "
     "The bold CAT Trademark logo across the chest identifies this as authentic workwear.",
     "Caterpillar CAT men hoodie sweatshirt"),

    (234,'APP-LULU-ALIGN-046', 118.00, 0.22, 0.40, 110,
     "Lululemon Align High-Rise Pant 28 inch",
     "Lululemon Align High Rise Pant 28 inch",
     "Lululemon Align Pant is made from buttery-soft Nulu fabric — so light it feels like "
     "a second skin — with four-way stretch and moisture-wicking properties. The high-rise "
     "waistband smoothly contours the waist without digging in, and the 28-inch inseam "
     "length is ideal for most heights. A hidden waistband pocket holds a key or card.",
     "Lululemon align leggings high rise"),

    (235,'APP-ARCTERYX-ATOM-047', 379.99, 0.22, 0.38, 60,
     "Arc'teryx Men's Atom Hoody Lightweight Insulated Jacket",
     "Arcteryx Mens Atom Hoody Lightweight Insulated Jacket",
     "Arc'teryx Atom Hoody uses Coreloft Compact 60 insulation for lightweight warmth with "
     "excellent compressibility. The Torrent stretch-woven face fabric is breathable and "
     "resistant to abrasion, while Polartec Power Stretch panels under the arms and along "
     "the sides enhance mobility. A helmet-compatible hood and two zip hand pockets complete "
     "this versatile midlayer for mountain activities.",
     "Arc'teryx atom hoody men jacket"),

    (236,'APP-NIKE-RDASH-048', 109.99, 0.20, 0.44, 135,
     "Nike Men's Therma-FIT ADV Running Division Phenom Pants",
     "Nike Mens Therma-FIT Running Pants",
     "Nike Therma-FIT technology helps manage your body's natural heat to keep you "
     "comfortable in cold-weather runs. These running pants feature reflective details "
     "for low-light visibility, secure zip pockets, and tapered legs that reduce excess "
     "fabric for a streamlined feel. Elastic waistband with internal drawstring for a "
     "secure, adjustable fit.",
     "Nike men running pants therma fit"),

    (237,'APP-ROOTS-COOPBVR-049', 98.00, 0.20, 0.44, 145,
     "Roots Unisex Original Roots Sweatpant",
     "Roots Unisex Original Sweatpants",
     "Roots Original Sweatpants are made from a proprietary salt-and-pepper fleece blend "
     "that has been a Canadian staple since 1973. The relaxed fit features an elastic "
     "waistband with external drawstring, two side pockets, and the iconic Roots beaver "
     "patch on the left hip. These timeless sweatpants offer unbeatable comfort for "
     "lounging, light activities, or casual Canadian style.",
     "Roots Canada original sweatpants"),

    (238,'APP-HANES-COMF-050', 24.99, 0.18, 0.52, 500,
     "Hanes Men's ComfortSoft Short Sleeve T-Shirt 6-Pack Value Pack",
     "Hanes Mens ComfortSoft T-Shirts 6-Pack",
     "Hanes ComfortSoft Men's T-Shirts are made from a tagless soft jersey knit that "
     "stays soft wash after wash. The crew neck design features a lay-flat collar that "
     "maintains its shape and is reinforced at the neck and shoulders. This 6-pack value "
     "set provides excellent everyday comfort and is available in white, assorted, and "
     "classic solid colours.",
     "Hanes men comfortsoft t-shirt 6 pack"),
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

def sanitize_folder(name: str) -> str:
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
    encoded = query.replace(' ', '+')
    html = fetch_page(session, f"https://www.amazon.ca/s?k={encoded}")
    if not html:
        return []
    soup = BeautifulSoup(html, 'lxml')
    results = []
    for card in soup.select('[data-component-type="s-search-result"]'):
        asin = card.get('data-asin', '')
        if not asin:
            continue
        h2_link  = card.select_one('h2 a')
        title_tag = card.select_one('h2 a span') or card.select_one('h2 span')
        if h2_link and h2_link.get('aria-label'):
            title = h2_link['aria-label'].strip()
        elif title_tag:
            title = title_tag.get_text(strip=True)
        else:
            continue
        link_tag = card.select_one('h2 a.a-link-normal') or card.select_one('a[href*="/dp/"]')
        href = link_tag['href'] if link_tag and link_tag.get('href') else f'/dp/{asin}'
        from urllib.parse import urljoin
        product_url = urljoin("https://www.amazon.ca", href.split('?')[0])
        if len(title) >= 10:
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
                urls = list(json.loads(img.get('data-a-dynamic-image', '{}')).keys())
                image_urls.extend(urls)
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
            seen.add(u); clean.append(u)
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
    params = {"cpanel_jsonapi_version":"2","cpanel_jsonapi_module":module,"cpanel_jsonapi_func":func}
    try:
        r = requests.post(CPANEL_API_URL, headers=CPANEL_HEADERS, params=params,
                          data=data or {}, files=files, verify=False, timeout=60)
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}

def cpanel_ok(res):
    return res.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1

def mkdir_remote(parent, name):
    """Create remote dir by UNENCODED name — critical to avoid %20 literal dirs."""
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
            try: out[e["file"]] = int(e.get("size") or 0)
            except: out[e["file"]] = 0
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

def esc(v):
    if v is None:
        return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"

def generate_sql(product_rows):
    """Write sql/insert_35_apparel.sql from the collected product data."""
    lines = []
    def w(s=''):
        lines.append(s)

    w('-- ============================================================')
    w('-- INSERT 35 best-selling Apparel products + pricing + images')
    w(f'-- Generated: {NOW[:10]}')
    w('-- Products  : 35 rows  (product_number 204-238)')
    w('-- Pricing   : 105 rows (Retail + Promo + Wholesale per product)')
    w('-- Images    : 175 rows (5 images per product)')
    w('-- Category  : Apparel  (7632ef73-7a4a-4320-b5d8-a2bb72bd8c03)')
    w('-- Currency  : CAD')
    w('-- ============================================================')
    w()

    # ── products ──────────────────────────────────────────────────────────────
    w('-- ============================================================')
    w('-- SECTION 1: products (35 rows)')
    w('-- ============================================================')
    w()
    for pr in product_rows:
        pid, num, sku, name, desc, retail, ws, promo, stock, images = (
            pr['product_id'], pr['product_number'], pr['sku'],
            pr['name'], pr['description'], pr['retail'], pr['ws'],
            pr['promo'], pr['stock'], pr['images'])
        w(f"-- [{num}] {name[:72]}")
        w("INSERT INTO products")
        w("  (product_id, product_number, product_name, sku, description,")
        w("   category_id, currency_code, stock_quantity, is_active, is_synthetic,")
        w("   created_at, updated_at)")
        w("VALUES")
        w(f"  ({esc(pid)}, {num}, {esc(name)}, {esc(sku)}, {esc(desc)},")
        w(f"   {esc(APPAREL_CAT_ID)}, 'CAD', {stock}, TRUE, FALSE,")
        w(f"   {esc(NOW)}, {esc(NOW)})")
        w("ON CONFLICT (sku) DO UPDATE SET")
        w("  product_name   = EXCLUDED.product_name,")
        w("  description    = EXCLUDED.description,")
        w("  stock_quantity = EXCLUDED.stock_quantity,")
        w("  updated_at     = EXCLUDED.updated_at;")
        w()

    # ── product_pricing ────────────────────────────────────────────────────────
    w()
    w('-- ============================================================')
    w('-- SECTION 2: product_pricing (105 rows)')
    w('-- ============================================================')
    w()
    w('DELETE FROM product_pricing')
    w('WHERE product_id IN (')
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 204 AND 238')
    w(');')
    w()
    for pr in product_rows:
        pid, num, sku = pr['product_id'], pr['product_number'], pr['sku']
        for ptype, pval in [('Retail', pr['retail']), ('Promo', pr['promo']), ('Wholesale', pr['ws'])]:
            ppid = str(uuid.uuid4())
            w(f"-- [{num}] {sku}  {ptype}: ${pval:.2f}")
            w("INSERT INTO product_pricing")
            w("  (product_pricing_id, product_id, price_type, price_value, currency_code,")
            w("   is_synthetic, created_at, updated_at)")
            w("VALUES")
            w(f"  ({esc(ppid)}, {esc(pid)}, {esc(ptype)}, {pval:.2f}, 'CAD',")
            w(f"   FALSE, {esc(NOW)}, {esc(NOW)});")
            w()

    # ── product_image ──────────────────────────────────────────────────────────
    w()
    w('-- ============================================================')
    w('-- SECTION 3: product_image (175 rows)')
    w('-- ============================================================')
    w()
    w('DELETE FROM product_image')
    w('WHERE product_id IN (')
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 204 AND 238')
    w(');')
    w()
    for pr in product_rows:
        pid, num, sku, name = pr['product_id'], pr['product_number'], pr['sku'], pr['name']
        for img_file, sort_order in pr['images']:
            piid = str(uuid.uuid4())
            folder_enc = quote(pr['folder_name'], safe='')
            img_url = f"https://agentorc.ca/image/Apparel/{folder_enc}/{img_file}"
            alt = f"{name[:80]} - image {sort_order}"
            w(f"-- [{num}] {sku}  sort_order={sort_order}")
            w("INSERT INTO product_image")
            w("  (product_image_id, product_id, image_url, sort_order, alt_text, created_at)")
            w("VALUES")
            w(f"  ({esc(piid)}, {esc(pid)}, {esc(img_url)}, {sort_order}, {esc(alt)}, {esc(NOW)});")
            w()

    with open(SQL_OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"\nSQL saved → {SQL_OUT}")


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

    local_apparel_dir = os.path.join(IMAGE_BASE, "Apparel")
    remote_apparel_dir = f"{REMOTE_BASE}/Apparel"
    os.makedirs(local_apparel_dir, exist_ok=True)

    succeeded = []
    failed    = []
    product_rows = []   # collect for SQL generation

    for (num, sku, retail, ws_pct, promo_ratio, stock,
         name, folder_name, desc, search_query) in PRODUCTS:

        print(f"\n{'='*70}")
        print(f"[{num}] {name[:70]}")

        folder       = sanitize_folder(folder_name)
        local_dir    = os.path.join(local_apparel_dir, folder)
        # Remote dir uses UNENCODED name (spaces) — Apache decodes %20 → space
        remote_dir   = f"{remote_apparel_dir}/{folder}"
        folder_enc   = quote(folder, safe='')   # only used in DB URLs
        os.makedirs(local_dir, exist_ok=True)

        # ── Step 1: Download images ──────────────────────────────────────────
        existing_imgs = sorted([
            f for f in os.listdir(local_dir)
            if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))
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
                if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))
            ])
            print(f"  Total images: {len(existing_imgs)}")

        # ── Step 2: Upload to cPanel with UNENCODED remote dir ───────────────
        print(f"  Uploading to cPanel: {folder[:55]}")
        mkdir_remote(remote_apparel_dir, folder)   # pass name with spaces!

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
                  APPAREL_CAT_ID, stock, NOW, NOW))
            actual_pid = cur.fetchone()[0]

            cur.execute('DELETE FROM product_image   WHERE product_id=%s', (actual_pid,))
            cur.execute('DELETE FROM product_pricing WHERE product_id=%s', (actual_pid,))

            img_files = sorted([
                f for f in os.listdir(local_dir)
                if f.lower().endswith(('.jpg','.jpeg','.png','.webp'))
            ])[:IMAGES_PER]

            images_data = []
            for sort_order, img_file in enumerate(img_files, 1):
                img_url = f"https://agentorc.ca/image/Apparel/{folder_enc}/{img_file}"
                cur.execute('''
                    INSERT INTO product_image
                      (product_image_id, product_id, image_url, sort_order, alt_text, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                ''', (str(uuid.uuid4()), actual_pid, img_url, sort_order,
                      f"{name[:80]} - image {sort_order}", NOW))
                images_data.append((img_file, sort_order))

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

            product_rows.append({
                'product_id':    str(actual_pid),
                'product_number': num,
                'sku':           sku,
                'name':          name,
                'description':   desc,
                'folder_name':   folder,
                'retail':        retail,
                'ws':            ws,
                'promo':         promo,
                'stock':         stock,
                'images':        images_data,
            })

        except Exception as e:
            conn.rollback()
            print(f"  DB ERROR: {e}")
            import traceback; traceback.print_exc()
            failed.append(sku)

        session.headers['User-Agent'] = random.choice(USER_AGENTS)

    # ── Generate SQL file ─────────────────────────────────────────────────────
    if product_rows:
        generate_sql(product_rows)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"DONE. Succeeded: {len(succeeded)}/{len(PRODUCTS)}")
    if failed:
        print(f"Failed SKUs: {failed}")
    conn.close()


if __name__ == "__main__":
    main()
