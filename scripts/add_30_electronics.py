"""
Add 30 best-selling Electronics products:
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally to image/Electronics/{Product Name}/image_N.jpg
  3. Uploads to agentorc.ca via cPanel UAPI
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)

Run from the project root:
    python scripts/add_30_electronics.py
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os, re, json, time, random, uuid, shutil, requests
from urllib.parse import urljoin, quote
from datetime import datetime, timezone
import psycopg2
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────
IMAGE_BASE   = r"D:\a\crm_agent\image"
IMAGES_PER   = 5
DELAY_MIN    = 2.0
DELAY_MAX    = 4.5
NOW          = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")

# cPanel upload config
CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
REMOTE_BASE  = "/home2/agentorc/public_html/image"

# DB config (Railway)
DB_HOST = "shinkansen.proxy.rlwy.net"
DB_PORT = 26832
DB_NAME = "railway"
DB_USER = "postgres"
DB_PASS = "SimKpntYtoGdLWdVsXglunQqHZMHXUfQ"

ELECTRONICS_CAT_ID = "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 30 Best-selling Electronics products ─────────────────────────────────────
# Format: (product_number, sku, retail_price_cad, ws_discount_pct, promo_ratio,
#          stock, name, folder_name, description, amazon_search_query)
# ws_discount_pct: wholesale is retail * (1 - ws_discount_pct), e.g. 0.20 = 20% off
# promo_ratio: promo = retail - (retail - ws) * promo_ratio, ratio in (0, 1)
PRODUCTS = [
    (174, 'ELEC-APPL-IPH15-018', 1299.00, 0.20, 0.40, 85,
     "Apple iPhone 15 Pro 256GB Natural Titanium Unlocked",
     "Apple iPhone 15 Pro 256GB Natural Titanium",
     "The Apple iPhone 15 Pro features a lightweight titanium design with a 6.1-inch Super Retina XDR "
     "display and the powerful A17 Pro chip for console-quality gaming. It includes a pro camera system "
     "with 48MP Main, 12MP Ultra Wide, and 12MP Telephoto lenses supporting 3x optical zoom, plus a "
     "USB-C port for up to 2x faster data transfer.",
     "Apple iPhone 15 Pro titanium"),

    (175, 'ELEC-SAMS-S24U-019', 1499.99, 0.22, 0.38, 72,
     "Samsung Galaxy S24 Ultra 256GB Titanium Black Unlocked",
     "Samsung Galaxy S24 Ultra 256GB Titanium Black",
     "The Samsung Galaxy S24 Ultra features a built-in S Pen for natural writing and sketching, a "
     "200MP pro-grade camera with 100x Space Zoom, and a 6.8-inch QHD+ Dynamic AMOLED 2X display "
     "with 120Hz refresh rate. Powered by Snapdragon 8 Gen 3, it delivers AI-powered photo editing, "
     "live translation, and all-day battery life with a 5000mAh cell.",
     "Samsung Galaxy S24 Ultra smartphone"),

    (176, 'ELEC-APPL-IPDP-020', 1329.00, 0.18, 0.42, 60,
     "Apple iPad Pro 11-inch (M4) 256GB Wi-Fi Space Black",
     "Apple iPad Pro 11-inch M4 256GB Wi-Fi",
     "The Apple iPad Pro 11-inch with M4 chip features the world's most advanced display — an "
     "Ultra Retina XDR OLED with tandem OLED technology reaching up to 1000 nits of full-screen "
     "brightness. The M4 chip delivers exceptional CPU and GPU performance, and the device is "
     "the thinnest Apple product ever at just 5.3mm.",
     "Apple iPad Pro 11 inch M4"),

    (177, 'ELEC-SAMS-65TV-021', 898.00, 0.20, 0.45, 35,
     "Samsung 65-Inch Crystal UHD 4K Smart TV UN65CU8000FXZC",
     "Samsung 65 Inch Crystal UHD 4K Smart TV CU8000",
     "The Samsung 65-inch CU8000 Crystal UHD 4K Smart TV delivers vivid detail with 4K UHD "
     "resolution and Crystal Processor 4K that transforms content in real time. It features "
     "PurColor technology for an expansive color spectrum, Auto Game Mode (ALLM) for instant "
     "gaming response, and a clean one remote to control everything.",
     "Samsung 65 inch 4K TV"),

    (178, 'ELEC-SONY-WH1X-022', 449.99, 0.22, 0.40, 110,
     "Sony WH-1000XM5 Wireless Industry Leading Noise Canceling Headphones",
     "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
     "Sony WH-1000XM5 headphones feature industry-leading noise cancellation with eight microphones "
     "and two processors, delivering up to 30 hours of battery life with quick charging (3 min = "
     "3 hours). Speak-to-Chat automatically pauses music when you speak, while Precise Voice Pickup "
     "technology ensures crystal-clear calls even in noisy environments.",
     "Sony WH-1000XM5 headphones"),

    (179, 'ELEC-BOSE-QCUL-023', 449.00, 0.20, 0.38, 95,
     "Bose QuietComfort Ultra Wireless Noise Cancelling Headphones",
     "Bose QuietComfort Ultra Wireless Headphones",
     "Bose QuietComfort Ultra headphones deliver the brand's best noise cancellation ever with "
     "Immersive Audio that places sound all around you. CustomTune technology automatically "
     "personalizes both sound and ANC to the exact geometry of your ear, offering up to 24 hours "
     "of battery life with a simple 15-minute quick charge providing up to 2.5 hours of playback.",
     "Bose QuietComfort Ultra headphones"),

    (180, 'ELEC-NINT-SWOL-024', 449.99, 0.15, 0.50, 130,
     "Nintendo Switch OLED Model White with Joy-Con",
     "Nintendo Switch OLED Model White",
     "The Nintendo Switch OLED Model features a vibrant 7-inch OLED screen for vivid colors and "
     "sharp contrast, a wide adjustable stand for comfortable tabletop play, and 64GB of internal "
     "storage. With a wired LAN port in the dock and enhanced audio output, it delivers an "
     "elevated Nintendo Switch experience at home and on the go.",
     "Nintendo Switch OLED white"),

    (181, 'ELEC-SONY-PS5S-025', 649.99, 0.17, 0.45, 55,
     "Sony PlayStation 5 Slim Disc Edition Console",
     "Sony PlayStation 5 Slim Disc Edition",
     "The PlayStation 5 Slim is 30% smaller than the original PS5, featuring a custom AMD CPU and "
     "GPU delivering 4K gaming at up to 120fps. The ultra-high speed SSD with 1TB storage enables "
     "lightning-fast load times, while the 3D Audio engine and DualSense wireless controller "
     "with haptic feedback and adaptive triggers create unprecedented immersion.",
     "Sony PS5 Slim console"),

    (182, 'ELEC-XBSX-1TB-026', 649.99, 0.17, 0.42, 48,
     "Microsoft Xbox Series X 1TB Console",
     "Microsoft Xbox Series X 1TB Gaming Console",
     "Xbox Series X is Microsoft's most powerful console ever, delivering true 4K gaming at up to "
     "120fps with DirectX ray tracing and Variable Rate Shading. The custom 1TB SSD and Xbox "
     "Velocity Architecture virtually eliminate load times, while Smart Delivery ensures you play "
     "the best version of every game for free.",
     "Xbox Series X console"),

    (183, 'ELEC-APPL-WS10-027', 599.00, 0.18, 0.40, 145,
     "Apple Watch Series 10 GPS 46mm Jet Black Aluminum Case",
     "Apple Watch Series 10 GPS 46mm Jet Black",
     "Apple Watch Series 10 is the thinnest Apple Watch ever with the largest display yet, featuring "
     "a new wide-angle LTPO OLED display with up to 2000 nits brightness. It includes advanced "
     "health sensors for ECG, blood oxygen monitoring, and sleep apnea detection, with up to "
     "18 hours of battery life and faster charging than ever before.",
     "Apple Watch Series 10"),

    (184, 'ELEC-GOOG-PX9P-028', 1299.00, 0.20, 0.38, 80,
     "Google Pixel 9 Pro 256GB Obsidian Unlocked Android Phone",
     "Google Pixel 9 Pro 256GB Obsidian",
     "Google Pixel 9 Pro features a 6.3-inch Super Actua OLED display with 2856x1280 resolution and "
     "up to 3000 nits peak brightness. Powered by Google Tensor G4 and 16GB RAM, it delivers "
     "AI-powered photography with a 50MP main camera, 48MP ultrawide, and 48MP telephoto with "
     "5x optical zoom, plus 7 years of OS, security, and Pixel Drop updates.",
     "Google Pixel 9 Pro phone"),

    (185, 'ELEC-DJI-MINI4-029', 959.00, 0.22, 0.40, 42,
     "DJI Mini 4 Pro Fly More Combo (DJI RC-N2)",
     "DJI Mini 4 Pro Drone Fly More Combo",
     "DJI Mini 4 Pro weighs under 249g and shoots 4K/60fps HDR video with a 1/1.3-inch CMOS sensor "
     "and f/1.7 aperture for exceptional low-light performance. It features omnidirectional obstacle "
     "sensing, 10-bit D-Log M color profile, 360° horizontal panoramas, and up to 34 minutes of "
     "flight time, making it ideal for professional-grade aerial content creation.",
     "DJI Mini 4 Pro drone"),

    (186, 'ELEC-GPRO-H13B-030', 599.99, 0.20, 0.42, 67,
     "GoPro HERO13 Black Action Camera with Enduro Battery",
     "GoPro HERO13 Black Action Camera",
     "GoPro HERO13 Black captures stunning 5.3K60 and 4K120 video with HyperSmooth 6.0 stabilization "
     "and a new HB mount system compatible with all GoPro ecosystem accessories. Waterproof to 10m "
     "without a housing, it features a 1/1.9-inch sensor, 27MP photos, Burst RAW support, and up "
     "to 70 minutes of recording on the included Enduro battery.",
     "GoPro HERO13 Black camera"),

    (187, 'ELEC-CANO-R50K-031', 1099.99, 0.20, 0.40, 38,
     "Canon EOS R50 Mirrorless Camera with RF-S 18-45mm STM Lens Kit",
     "Canon EOS R50 Mirrorless Camera with 18-45mm Lens",
     "The Canon EOS R50 is a lightweight APS-C mirrorless camera featuring a 24.2MP sensor and "
     "DIGIC X processor for fast autofocus with subject-tracking eye detection across people, "
     "animals, and vehicles. It shoots 4K video at 30fps with Cinema EOS-style movie cropping "
     "and includes Bluetooth and Wi-Fi for seamless image transfer to smart devices.",
     "Canon EOS R50 mirrorless camera"),

    (188, 'ELEC-APPL-MBA13-032', 1499.00, 0.18, 0.45, 55,
     "Apple MacBook Air 13-inch Apple M3 Chip 16GB RAM 256GB SSD Midnight",
     "Apple MacBook Air 13 inch M3 Midnight",
     "MacBook Air 13-inch with M3 chip delivers up to 18 hours of battery life and blazing-fast "
     "performance for everyday tasks, creative projects, and AI workloads. The 13.6-inch Liquid "
     "Retina display supports up to two external displays when the lid is closed, and Wi-Fi 6E "
     "offers faster wireless performance than ever.",
     "Apple MacBook Air 13 M3"),

    (189, 'ELEC-ASUS-ROG16-033', 1999.99, 0.22, 0.38, 28,
     "ASUS ROG Strix G16 16-inch Gaming Laptop Intel Core i9 RTX 4070 16GB RAM",
     "ASUS ROG Strix G16 Gaming Laptop Core i9 RTX 4070",
     "The ASUS ROG Strix G16 packs an Intel Core i9-14900HX processor with NVIDIA GeForce RTX 4070 "
     "graphics into a sleek 16-inch chassis with a 2560x1600 QHD+ 240Hz display. MUX Switch "
     "technology boosts GPU performance by up to 30%, while the ROG Intelligent Cooling system "
     "with liquid metal thermal compound keeps temperatures low during intense gaming sessions.",
     "ASUS ROG gaming laptop"),

    (190, 'ELEC-RAZE-DEA3-034', 149.99, 0.20, 0.48, 180,
     "Razer DeathAdder V3 HyperSpeed Wireless Gaming Mouse",
     "Razer DeathAdder V3 HyperSpeed Wireless Mouse",
     "The Razer DeathAdder V3 HyperSpeed is an ultra-lightweight wireless gaming mouse at just 63g, "
     "featuring the Focus X 26K DPI optical sensor for snappy and precise tracking. HyperSpeed "
     "Wireless technology provides a 25% faster connection than competing wireless technologies, "
     "with up to 300 hours of battery life on a single AA battery.",
     "Razer DeathAdder V3 wireless mouse"),

    (191, 'ELEC-RAZE-BW4M-035', 249.99, 0.20, 0.42, 120,
     "Razer BlackWidow V4 Mechanical Gaming Keyboard with Razer Green Switches",
     "Razer BlackWidow V4 Mechanical Gaming Keyboard",
     "Razer BlackWidow V4 features Razer Green Switches with tactile click feedback and a 1.9mm "
     "actuation point for satisfying, precise keystrokes. Doubleshot ABS Keycaps with Razer Chroma "
     "RGB provide vibrant per-key lighting from 16.8 million colors, while the magnetic wrist rest "
     "with leatherette padding offers ergonomic support for extended gaming sessions.",
     "Razer BlackWidow V4 keyboard"),

    (192, 'ELEC-SONY-DS5C-036', 89.99, 0.15, 0.50, 220,
     "Sony PS5 DualSense Wireless Controller - Midnight Black",
     "Sony DualSense Wireless Controller Midnight Black",
     "The DualSense wireless controller for PS5 features haptic feedback with dynamic sensations "
     "you can feel during gameplay and adaptive triggers that provide varying levels of resistance. "
     "Built-in microphone and headphone jack let you chat without a headset, while the built-in "
     "rechargeable battery and USB Type-C port allow easy charging.",
     "PS5 DualSense controller"),

    (193, 'ELEC-ASUS-RTAX-037', 349.99, 0.22, 0.40, 75,
     "ASUS RT-AX86U Dual Band WiFi 6 Router AX5700 Gaming Router",
     "ASUS RT-AX86U WiFi 6 Gaming Router AX5700",
     "ASUS RT-AX86U is a high-performance dual-band WiFi 6 router delivering combined speeds up to "
     "5700 Mbps with 4x4 MU-MIMO and OFDMA technology for handling multiple devices simultaneously. "
     "ASUS Mobile Game Mode dedicates maximum bandwidth for mobile gaming, while Adaptive QoS and "
     "port forwarding ensure lag-free gaming across all connected devices.",
     "ASUS RT-AX86U router"),

    (194, 'ELEC-AMZN-FTV4M-038', 89.99, 0.15, 0.50, 250,
     "Amazon Fire TV Stick 4K Max (2nd Gen) with Wi-Fi 6E Support",
     "Amazon Fire TV Stick 4K Max 2nd Gen",
     "Fire TV Stick 4K Max (2nd Gen) features Wi-Fi 6E support for blazing-fast streaming and "
     "an octa-core processor that's 30% more powerful than the previous generation. Supports "
     "4K Ultra HD, Dolby Vision, HDR10+, and Dolby Atmos for cinematic picture and sound, "
     "with Alexa built-in for hands-free voice control of compatible smart home devices.",
     "Amazon Fire TV Stick 4K Max"),

    (195, 'ELEC-ANKR-737-039', 129.99, 0.20, 0.45, 165,
     "Anker 737 Power Bank 24000mAh 140W USB-C Portable Charger",
     "Anker 737 Power Bank 24000mAh 140W",
     "Anker 737 Power Bank delivers 140W total output through two USB-C and one USB-A port, "
     "capable of fully charging a MacBook Air in just 1.3 hours. The 24000mAh capacity provides "
     "multiple charges for laptops, smartphones, and tablets, while the smart digital display "
     "shows wattage, capacity remaining, and estimated time until full charge.",
     "Anker power bank 140W laptop"),

    (196, 'ELEC-SAMS-55QN-040', 1299.99, 0.22, 0.38, 22,
     "Samsung 55-inch QN90D Neo QLED 4K Smart TV (2024)",
     "Samsung 55 inch QN90D Neo QLED 4K TV",
     "Samsung QN90D Neo QLED 4K TV uses Quantum Mini LEDs and Neo Quantum Processor 4K to deliver "
     "precise brightness control and exceptional contrast with deep blacks and vibrant highlights. "
     "Anti-Reflection technology reduces glare for a more immersive viewing experience, while "
     "4K AI Upscaling Pro enhances lower resolution content to near-4K quality.",
     "Samsung 55 inch Neo QLED TV"),

    (197, 'ELEC-JBL-CHG5-041', 219.99, 0.20, 0.45, 140,
     "JBL Charge 5 Portable Waterproof Bluetooth Speaker with Powerbank",
     "JBL Charge 5 Portable Bluetooth Speaker",
     "JBL Charge 5 delivers bold JBL Pro Sound with a racetrack-shaped woofer and separate tweeter "
     "for powerful stereo sound with surprisingly deep bass. IP67 waterproof and dustproof, it "
     "can be fully submerged in up to 1 meter of water for 30 minutes. The 7500mAh battery provides "
     "over 20 hours of playtime and doubles as a USB powerbank for charging your devices.",
     "JBL Charge 5 bluetooth speaker"),

    (198, 'ELEC-FITB-CHG6-042', 199.99, 0.20, 0.45, 175,
     "Fitbit Charge 6 Advanced Fitness Tracker with Google Apps, GPS, Black",
     "Fitbit Charge 6 Fitness Tracker Black",
     "Fitbit Charge 6 features built-in GPS for real-time pace and distance tracking plus Google "
     "Maps turn-by-turn directions on your wrist. It continuously tracks heart rate, sleep stages, "
     "and stress levels with EDA sensor, while Google Wallet lets you pay with your wrist. "
     "Get up to 7 days of battery life and compatibility with Google Maps and YouTube Music.",
     "Fitbit Charge 6 fitness tracker"),

    (199, 'ELEC-GARM-VA5-043', 399.99, 0.20, 0.40, 92,
     "Garmin Vivoactive 5 GPS Smartwatch with Health Monitoring",
     "Garmin Vivoactive 5 GPS Smartwatch",
     "Garmin Vivoactive 5 GPS smartwatch features an AMOLED display with 11 days of battery life "
     "in smartwatch mode, tracking over 25 preloaded indoor and outdoor sports activities. Advanced "
     "health monitoring includes Body Battery energy tracking, HRV status, sleep score, and daily "
     "suggested workouts, with Garmin Pay for contactless payments on your wrist.",
     "Garmin Vivoactive 5 smartwatch"),

    (200, 'ELEC-EPSO-ET28-044', 329.99, 0.18, 0.45, 68,
     "Epson EcoTank ET-2800 Wireless Color Inkjet All-in-One Supertank Printer",
     "Epson EcoTank ET-2800 Wireless Inkjet All-in-One Printer",
     "Epson EcoTank ET-2800 eliminates expensive ink cartridges with its supersized ink tanks that "
     "can be refilled with low-cost ink bottles — included ink provides up to 2 years of printing "
     "with up to 4500 pages black and 7500 pages color. Features wireless printing, auto 2-sided "
     "printing, borderless 4x6-inch photos, and voice-activated printing via Alexa.",
     "Epson EcoTank ET-2800 printer"),

    (201, 'ELEC-RING-VDP2-045', 249.99, 0.20, 0.42, 88,
     "Ring Video Doorbell Pro 2 with Head-to-Toe 3D Motion Detection",
     "Ring Video Doorbell Pro 2",
     "Ring Video Doorbell Pro 2 delivers 1536p HD video with an enhanced 150-degree horizontal field "
     "of view plus Bird's Eye View via radar that lets you see the path someone took to your door. "
     "3D Motion Detection with radar creates a customizable detection zone so you only get alerts "
     "when someone enters the area that matters, with color night vision for clear footage 24/7.",
     "Ring Video Doorbell Pro 2"),

    (202, 'ELEC-PHIL-HUE4-046', 229.99, 0.18, 0.45, 115,
     "Philips Hue Smart Bulb Starter Kit A19 White and Color Ambiance 4-Pack",
     "Philips Hue Smart Bulb Starter Kit 4-Pack White Color Ambiance",
     "Philips Hue White and Color Ambiance Starter Kit includes 4 A19 smart bulbs and a Hue Bridge "
     "that enables control of up to 50 lights. Choose from 16 million colors and thousands of "
     "shades of white to create the perfect atmosphere for any moment. Schedule lights to turn on "
     "and off automatically and integrate with Alexa, Google Assistant, and Apple HomeKit.",
     "Philips Hue smart bulb starter kit"),

    (203, 'ELEC-WDB-SN85-047', 259.99, 0.22, 0.40, 98,
     "WD_BLACK 2TB SN850X NVMe M.2 2280 PCIe Gen4 Internal Gaming SSD",
     "WD Black SN850X 2TB NVMe M.2 SSD",
     "WD_BLACK SN850X NVMe SSD delivers read speeds up to 7300 MB/s and write speeds up to "
     "6600 MB/s, utilizing PCIe Gen 4 technology for lightning-fast game load times. The "
     "new Game Mode 2.0 uses AI to learn your library and automatically pre-load and cache "
     "games for even faster launches, backed by a 5-year limited warranty.",
     "WD Black SN850X 2TB SSD"),
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
    """Make a string safe for use as a Windows folder name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.rstrip(' ,.')
    return name[:120]


def fetch_page(session, url: str, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.text
            if r.status_code in (503, 429):
                wait = 15 + attempt * 10
                print(f"  HTTP {r.status_code} – waiting {wait}s (attempt {attempt+1})")
                time.sleep(wait)
            else:
                print(f"  HTTP {r.status_code} for {url}")
        except Exception as e:
            print(f"  Request error: {e}")
        time.sleep(5)
    return None


def search_amazon(session, query: str) -> list:
    """Return list of {title, url} from Amazon.ca search results."""
    from bs4 import BeautifulSoup
    encoded = query.replace(' ', '+')
    url = f"https://www.amazon.ca/s?k={encoded}"
    html = fetch_page(session, url)
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
        if link_tag and link_tag.get('href'):
            href = link_tag['href']
        else:
            href = f"/dp/{asin}"
        product_url = urljoin("https://www.amazon.ca", href.split('?')[0])
        if len(title) >= 10:
            results.append({'title': title, 'url': product_url})
    return results


def get_product_images(session, product_url: str) -> list:
    """Return up to 5 high-res image URLs from an Amazon product page."""
    from bs4 import BeautifulSoup
    html = fetch_page(session, product_url)
    if not html:
        return []
    soup = BeautifulSoup(html, 'lxml')
    image_urls = []

    # Strategy 1: colorImages JSON blob in page scripts
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
                urls = list(json.loads(data).keys())
                image_urls.extend(urls)
            except Exception:
                pass

    # Strategy 3: main product image
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
    seen = set()
    clean = []
    for u in image_urls:
        u = u.strip()
        if u and u not in seen and 'sprite' not in u and u.startswith('http'):
            seen.add(u)
            clean.append(u)

    return clean[:IMAGES_PER]


def download_image(session, url: str, dest_path: str) -> bool:
    try:
        r = session.get(url, timeout=25, stream=True)
        if r.status_code == 200 and len(r.content) > 2000:
            with open(dest_path, 'wb') as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"    [img dl error] {e}")
    return False


# ── cPanel upload helpers ─────────────────────────────────────────────────────

CPANEL_HEADERS = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}
CPANEL_API_URL = f"{CPANEL_HOST}/json-api/cpanel"


def cpanel_api(module, func, data=None, files=None):
    params = {
        "cpanel_jsonapi_version": "2",
        "cpanel_jsonapi_module": module,
        "cpanel_jsonapi_func": func,
    }
    try:
        r = requests.post(CPANEL_API_URL, headers=CPANEL_HEADERS, params=params,
                          data=data or {}, files=files, verify=False, timeout=60)
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}


def cpanel_ok(result) -> bool:
    return result.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1


def mkdir_remote(remote_path: str) -> bool:
    parent = remote_path.rsplit('/', 1)[0]
    name   = remote_path.rsplit('/', 1)[1]
    result = cpanel_api("Fileman", "mkdir", data={"path": parent, "name": name})
    if cpanel_ok(result):
        return True
    err = str(result.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"    [mkdir error] {remote_path}: {err}")
    return False


def upload_file_cpanel(local_path: str, remote_dir: str) -> bool:
    filename = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        result = cpanel_api(
            "Fileman", "uploadfiles",
            data={"dir": remote_dir, "overwrite": 1},
            files={"file-1": (filename, f, "application/octet-stream")},
        )
    cr = result.get("cpanelresult", {})
    data = cr.get("data", [{}])
    uploads = data[0].get("uploads", []) if data else []
    if uploads and uploads[0].get("status") == 1:
        return True
    if data and data[0].get("succeeded", 0) == 1:
        return True
    reason = uploads[0].get("reason", "") if uploads else ""
    if "already exists" in reason.lower():
        return True
    err = cr.get("error") or reason or result
    print(f"    [upload error] {filename}: {err}")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    session = make_session()

    # Warm up Amazon session
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

    succeeded = []
    failed_products = []

    for (num, sku, retail, ws_pct, promo_ratio, stock, name, folder_name, desc, search_query) in PRODUCTS:
        print(f"\n{'='*70}")
        print(f"[{num}] {name[:70]}")

        # ── Step 1: Download images ───────────────────────────────────────────
        folder = sanitize_folder(folder_name)
        local_cat_dir = os.path.join(IMAGE_BASE, "Electronics")
        local_prod_dir = os.path.join(local_cat_dir, folder)
        os.makedirs(local_prod_dir, exist_ok=True)

        # Count existing images
        existing_imgs = [
            f for f in os.listdir(local_prod_dir)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
        ]
        if len(existing_imgs) >= IMAGES_PER:
            print(f"  [SKIP download] Already have {len(existing_imgs)} images")
        else:
            sleep()
            print(f"  Searching Amazon.ca for: {search_query}")
            candidates = search_amazon(session, search_query)
            print(f"  Found {len(candidates)} candidates")
            session.headers['User-Agent'] = random.choice(USER_AGENTS)

            downloaded = len(existing_imgs)
            for cand in candidates[:3]:
                if downloaded >= IMAGES_PER:
                    break
                print(f"  Trying: {cand['title'][:60]}")
                sleep()
                img_urls = get_product_images(session, cand['url'])
                print(f"  Found {len(img_urls)} images on page")

                for i, img_url in enumerate(img_urls):
                    if downloaded >= IMAGES_PER:
                        break
                    ext = '.jpg'
                    m = re.search(r'\.(jpg|jpeg|png|webp)(\?|$)', img_url, re.I)
                    if m:
                        ext = '.' + m.group(1).lower()
                    fname = os.path.join(local_prod_dir, f"image_{downloaded+1}{ext}")
                    ok = download_image(session, img_url, fname)
                    if ok:
                        downloaded += 1
                        print(f"    Downloaded {downloaded}/{IMAGES_PER}")

                if downloaded >= IMAGES_PER:
                    break

            existing_imgs = [
                f for f in os.listdir(local_prod_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ]
            print(f"  Total images in folder: {len(existing_imgs)}")

        # ── Step 2: Upload to cPanel ──────────────────────────────────────────
        folder_enc = quote(folder, safe='')
        remote_cat_dir  = f"{REMOTE_BASE}/Electronics"
        remote_prod_dir = f"{REMOTE_BASE}/Electronics/{folder_enc}"

        print(f"  Uploading to cPanel: {remote_prod_dir}")
        mkdir_remote(remote_cat_dir)
        mkdir_remote(remote_prod_dir)

        imgs_in_folder = sorted([
            f for f in os.listdir(local_prod_dir)
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
        ])
        upload_ok_count = 0
        for img_file in imgs_in_folder:
            local_path = os.path.join(local_prod_dir, img_file)
            ok = upload_file_cpanel(local_path, remote_prod_dir)
            status = "OK" if ok else "FAIL"
            print(f"    [{status}] {img_file}")
            if ok:
                upload_ok_count += 1

        print(f"  Uploaded {upload_ok_count}/{len(imgs_in_folder)} images")

        # ── Step 3: Database insert ───────────────────────────────────────────
        print(f"  Inserting into DB: {sku}")
        try:
            product_id = str(uuid.uuid4())

            # Upsert product
            cur.execute('''
                INSERT INTO products (product_id, product_number, product_name, sku, description,
                                      category_id, currency_code, stock_quantity, is_active, is_synthetic,
                                      created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'CAD', %s, TRUE, FALSE, %s, %s)
                ON CONFLICT (sku) DO UPDATE
                  SET product_name    = EXCLUDED.product_name,
                      description     = EXCLUDED.description,
                      stock_quantity  = EXCLUDED.stock_quantity,
                      updated_at      = EXCLUDED.updated_at
                RETURNING product_id
            ''', (product_id, num, name, sku, desc, ELECTRONICS_CAT_ID, stock, NOW, NOW))
            actual_pid = cur.fetchone()[0]

            # Delete old images + pricing (for re-runs)
            cur.execute('DELETE FROM product_image   WHERE product_id = %s', (actual_pid,))
            cur.execute('DELETE FROM product_pricing WHERE product_id = %s', (actual_pid,))

            # Insert images — use actual downloaded file names
            img_files = sorted([
                f for f in os.listdir(local_prod_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ])
            for sort_order, img_file in enumerate(img_files[:IMAGES_PER], 1):
                img_url = f"https://agentorc.ca/image/Electronics/{folder_enc}/{img_file}"
                cur.execute('''
                    INSERT INTO product_image (product_image_id, product_id, image_url,
                                               sort_order, alt_text, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (str(uuid.uuid4()), actual_pid, img_url, sort_order,
                      f"{name[:80]} - image {sort_order}", NOW))

            # Insert pricing
            ws    = round(retail * (1.0 - ws_pct), 2)
            promo = round(retail - (retail - ws) * promo_ratio, 2)
            for ptype, pval in [('Retail', retail), ('Promo', promo), ('Wholesale', ws)]:
                cur.execute('''
                    INSERT INTO product_pricing (product_pricing_id, product_id, price_type,
                                                 price_value, currency_code, is_synthetic,
                                                 created_at, updated_at)
                    VALUES (%s, %s, %s, %s, 'CAD', FALSE, %s, %s)
                ''', (str(uuid.uuid4()), actual_pid, ptype, pval, NOW, NOW))

            conn.commit()
            print(f"  DB OK  retail=${retail:.2f}  promo=${promo:.2f}  ws=${ws:.2f}  imgs={len(img_files[:IMAGES_PER])}")
            succeeded.append(sku)

        except Exception as e:
            conn.rollback()
            print(f"  DB ERROR: {e}")
            import traceback; traceback.print_exc()
            failed_products.append(sku)

        # Rotate user agent
        session.headers['User-Agent'] = random.choice(USER_AGENTS)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"DONE. Succeeded: {len(succeeded)}/{len(PRODUCTS)}")
    if failed_products:
        print(f"Failed: {failed_products}")
    conn.close()


if __name__ == "__main__":
    main()
