"""
Add 50 best-selling Electronics products (batch 2):
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally  → image/Electronics/{Folder Name}/image_N.jpg
  3. Uploads to agentorc.ca using UNENCODED folder names (spaces, not %20)
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)
  5. Generates sql/insert_50_electronics2.sql from live DB data

Run from project root:
    python scripts/add_50_electronics2.py
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
SQL_OUT      = r"D:\a\crm_agent\sql\insert_50_electronics2.sql"
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

ELEC_CAT_ID = "c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 50 Best-selling Electronics products (batch 2) ────────────────────────────
# (product_number, sku, retail_cad, ws_pct, promo_ratio, stock,
#  full_product_name, folder_name, description, amazon_search_query)
PRODUCTS = [
    (372, 'ELEC-APPL-IPH16-051', 1449.00, 0.12, 0.40, 65,
     "Apple iPhone 16 Pro 256GB Black Titanium Unlocked",
     "Apple iPhone 16 Pro 256GB Black Titanium Unlocked",
     "The Apple iPhone 16 Pro features a 6.3-inch Super Retina XDR display with ProMotion "
     "technology up to 120Hz and the powerful A18 Pro chip. The pro camera system includes "
     "a 48MP Fusion camera, 48MP Ultra Wide, and 5x Telephoto. Camera Control gives you "
     "intuitive one-click access to capture tools. USB-C with USB 3 speeds up to 20Gb/s. "
     "Aerospace-grade titanium design. Up to 33 hours video playback.",
     "Apple iPhone 16 Pro 256GB unlocked"),

    (373, 'ELEC-SAMS-S25U-052', 1649.99, 0.12, 0.40, 55,
     "Samsung Galaxy S25 Ultra 256GB Titanium Black Unlocked",
     "Samsung Galaxy S25 Ultra 256GB Titanium Black",
     "The Samsung Galaxy S25 Ultra features the integrated S Pen, a 6.9-inch QHD+ Dynamic "
     "AMOLED 2X display with 120Hz, and a 200MP pro-grade camera with 100x Space Zoom. "
     "Powered by Snapdragon 8 Elite for Galaxy, it delivers next-level AI features including "
     "Circle to Search, Live Translate, and Note Assist. Titanium frame, 5000mAh battery, "
     "and 45W fast charging.",
     "Samsung Galaxy S25 Ultra 256GB unlocked"),

    (374, 'ELEC-APPL-MBA15-053', 1899.00, 0.12, 0.40, 50,
     "Apple MacBook Air 15-inch M3 Chip, 8GB RAM, 256GB SSD, Midnight",
     "Apple MacBook Air 15-inch M3 8GB 256GB Midnight",
     "MacBook Air 15-inch with M3 chip delivers extraordinary performance in an impossibly "
     "thin fanless design. The 15.3-inch Liquid Retina display with 500 nits brightness "
     "and P3 wide colour is stunning for creative work. Up to 18 hours battery life. "
     "M3 chip with 8-core CPU and 10-core GPU handles demanding workloads with ease. "
     "Two Thunderbolt/USB 4 ports, MagSafe 3 charging, and Wi-Fi 6E.",
     "Apple MacBook Air 15 M3 chip laptop"),

    (375, 'ELEC-GOOG-PXL9P-054', 1299.00, 0.12, 0.40, 60,
     "Google Pixel 9 Pro 256GB Obsidian Unlocked",
     "Google Pixel 9 Pro 256GB Obsidian Unlocked",
     "Google Pixel 9 Pro features the Tensor G4 chip for advanced AI capabilities, a "
     "50MP main camera with 5x optical zoom, and a stunning 6.3-inch Actua display with "
     "2000 nits peak brightness. Google AI features include Magic Eraser, Best Take, "
     "and Live Translate. Seven years of OS, security, and Pixel Drop updates guaranteed. "
     "IP68 dust and water resistance. 4700mAh battery with 27W wired charging.",
     "Google Pixel 9 Pro 256GB unlocked"),

    (376, 'ELEC-APPL-WATS10-055', 629.00, 0.12, 0.42, 120,
     "Apple Watch Series 10 GPS 46mm Jet Black Aluminum Case",
     "Apple Watch Series 10 GPS 46mm Jet Black Aluminum",
     "Apple Watch Series 10 is the thinnest Apple Watch ever, with the largest display yet "
     "and the fastest charging. The wide-angle LTPO OLED display is up to 30% larger than "
     "Series 4. New sleep apnea detection notifies you of potential sleep apnea patterns. "
     "Advanced health sensors including electrical heart rate sensor and blood oxygen app. "
     "IP6X dust resistance and 50m water resistance. S10 SiP chip.",
     "Apple Watch Series 10 GPS 46mm"),

    (377, 'ELEC-SAMS-GW7-056', 449.99, 0.13, 0.42, 110,
     "Samsung Galaxy Watch7 44mm Graphite",
     "Samsung Galaxy Watch7 44mm Graphite",
     "Samsung Galaxy Watch7 features a 1.5-inch Super AMOLED display with 2000 nits "
     "brightness and the new Exynos W1000 chip — 3.4x faster than the previous generation. "
     "Advanced health tracking includes BioActive Sensor for heart rate, blood oxygen, "
     "and body composition. AI-powered Energy Score coaches you on lifestyle improvements. "
     "5ATM + IP68 water resistance. Up to 40 hours battery life in Power Saving mode.",
     "Samsung Galaxy Watch7 44mm"),

    (378, 'ELEC-SONY-WH1000-057', 449.99, 0.13, 0.42, 95,
     "Sony WH-1000XM5 Wireless Industry Leading Noise Canceling Headphones",
     "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
     "Sony WH-1000XM5 headphones feature industry-leading noise cancellation with eight "
     "microphones and two processors. The Integrated Processor V1 delivers superior noise "
     "cancellation and crystal clear hands-free calling. 30-hour battery life with quick "
     "charge (3 min = 3 hours). Ultra-comfortable lightweight design at 250g. "
     "Multipoint connection to two Bluetooth devices simultaneously. "
     "Hi-Res Audio and LDAC support for wireless high-quality audio.",
     "Sony WH-1000XM5 wireless noise canceling headphones"),

    (379, 'ELEC-APPL-AIRP4-058', 199.00, 0.13, 0.42, 180,
     "Apple AirPods 4 with Active Noise Cancellation",
     "Apple AirPods 4 with Active Noise Cancellation",
     "AirPods 4 feature Active Noise Cancellation for immersive sound and Transparency mode "
     "to hear the world around you. The new open-ear design delivers a comfortable, secure "
     "fit with no silicone tips. Powered by the H2 chip for advanced audio performance "
     "and computational audio. Up to 5 hours listening time with ANC on, 30 hours total "
     "with the MagSafe charging case. USB-C case charges wirelessly.",
     "Apple AirPods 4 active noise cancellation"),

    (380, 'ELEC-AMZN-FTVS4K-059', 89.99, 0.15, 0.44, 250,
     "Amazon Fire TV Stick 4K Max Streaming Device, Wi-Fi 6E",
     "Amazon Fire TV Stick 4K Max Streaming Device Wi-Fi 6E",
     "Fire TV Stick 4K Max is the most powerful Fire TV Stick with Wi-Fi 6E support for "
     "faster, more reliable streaming. Streams in vibrant 4K Ultra HD with support for "
     "Dolby Vision, HDR, HDR10+, and Dolby Atmos. Alexa Voice Remote lets you search "
     "and control your TV with your voice. Access over 1.5 million movies and TV episodes "
     "from Netflix, Prime Video, Disney+, Apple TV+, and more.",
     "Amazon Fire TV Stick 4K Max streaming device"),

    (381, 'ELEC-APPL-ATV4K-060', 249.00, 0.13, 0.42, 140,
     "Apple TV 4K (3rd Generation) Wi-Fi + Ethernet, 128GB",
     "Apple TV 4K 3rd Generation Wi-Fi Ethernet 128GB",
     "Apple TV 4K with the A15 Bionic chip delivers breathtaking 4K HDR picture quality "
     "with Dolby Vision and Dolby Atmos sound. The redesigned Siri Remote with clickpad "
     "makes navigation intuitive. Access all your favorite streaming services including "
     "Apple TV+, Netflix, Disney+, and more. Works seamlessly with iPhone for easy setup, "
     "AirPlay mirroring, and HomeKit smart home control. Thread networking built-in.",
     "Apple TV 4K 3rd generation"),

    (382, 'ELEC-NNTD-SWOL-061', 499.99, 0.12, 0.42, 90,
     "Nintendo Switch OLED Model, White",
     "Nintendo Switch OLED Model White",
     "Nintendo Switch OLED Model features a vibrant 7-inch OLED screen with vivid colours "
     "and crisp contrast for handheld play. The wide adjustable stand is perfect for "
     "tabletop mode. Enhanced audio from built-in speakers. A wired LAN port in the dock "
     "enables a stable internet connection for TV mode gaming. 64GB internal storage. "
     "Play as a home console, in tabletop mode, or on the go in handheld mode.",
     "Nintendo Switch OLED model white"),

    (383, 'ELEC-SONY-PS5SL-062', 699.99, 0.11, 0.40, 70,
     "Sony PlayStation 5 Slim Digital Edition Console",
     "Sony PlayStation 5 Slim Digital Edition Console",
     "PlayStation 5 Slim Digital Edition is 30% smaller than the original PS5 and includes "
     "a detachable disc drive (sold separately). Features the custom AMD GPU with ray tracing "
     "support, ultra-high-speed SSD for near-instant loading, and Tempest 3D AudioTech for "
     "immersive sound. DualSense controller with haptic feedback and adaptive triggers. "
     "Up to 8K graphics output. 1TB SSD storage.",
     "Sony PlayStation 5 Slim Digital Edition"),

    (384, 'ELEC-XBOX-SRX-063', 699.99, 0.11, 0.40, 75,
     "Microsoft Xbox Series X 1TB Console",
     "Microsoft Xbox Series X 1TB Console",
     "Xbox Series X delivers 4K gaming at up to 120FPS with ray tracing and DirectX 12 "
     "Ultimate support. The custom SSD enables near-instant load times and Quick Resume "
     "lets you seamlessly switch between multiple games. Xbox Game Pass Ultimate gives "
     "access to hundreds of games. Backward compatible with thousands of Xbox, Xbox 360, "
     "and Xbox One games. HDMI 2.1 output. 1TB Custom NVMe SSD.",
     "Microsoft Xbox Series X 1TB console"),

    (385, 'ELEC-GPRG-HERO13-064', 599.99, 0.13, 0.42, 85,
     "GoPro HERO13 Black Action Camera with 4K Ultra HD Video",
     "GoPro HERO13 Black Action Camera 4K Ultra HD",
     "GoPro HERO13 Black delivers HyperSmooth 6.0 stabilisation for ultra-smooth footage "
     "in virtually any condition. Shoot stunning 5.3K60 and 4K Ultra HD video, and up to "
     "27MP photos. New Enduro battery improves performance in extreme cold. Waterproof to "
     "10 minutes at 33ft (10m). 10-bit colour for cinematic post-production. "
     "HDR video up to 4K30. Compatible with all GoPro accessories and mounts.",
     "GoPro HERO13 Black action camera"),

    (386, 'ELEC-DJI-MINI4P-065', 959.99, 0.12, 0.41, 55,
     "DJI Mini 4 Pro Drone with 4K HDR Video, 3-Way Obstacle Sensing",
     "DJI Mini 4 Pro Drone 4K HDR Video",
     "DJI Mini 4 Pro is a lightweight sub-249g drone with pro-level capabilities. Shoots "
     "4K HDR video at 60fps and 48MP raw photos with a 1/1.3-inch CMOS sensor. "
     "Omnidirectional obstacle sensing keeps it safe in complex environments. "
     "Extended 34-minute max flight time. ActiveTrack 360 keeps your subject centered "
     "automatically. Transmission range up to 20km with O4 video transmission. "
     "No registration required in Canada (under 250g).",
     "DJI Mini 4 Pro drone"),

    (387, 'ELEC-SAMS-75QN9-066', 4499.99, 0.10, 0.38, 20,
     "Samsung 75-Inch Neo QLED 8K Smart TV QN75QN900D",
     "Samsung 75-Inch Neo QLED 8K Smart TV QN75QN900D",
     "Samsung 75-inch Neo QLED 8K TV uses Quantum Matrix Technology Pro with 14-bit "
     "dimming for precise brightness control across thousands of Mini LEDs. The Neural "
     "Quantum Processor 8K upscales all content to near-8K quality. Real 8K resolution "
     "with 33 million pixels. Dolby Atmos and Object Tracking Sound Pro deliver immersive "
     "audio from all directions. One Connect Box keeps cables tidy. Tizen OS.",
     "Samsung 75 inch Neo QLED 8K smart TV"),

    (388, 'ELEC-LG-OLED55C4-067', 1799.99, 0.11, 0.40, 35,
     "LG OLED55C4PSA 55-Inch OLED evo C4 4K Smart TV 2024",
     "LG OLED55C4 55-Inch OLED evo C4 4K Smart TV 2024",
     "LG OLED C4 features self-lit OLED evo pixels for perfect blacks, infinite contrast, "
     "and over a billion colours. The Alpha 9 AI Processor 4K Gen7 optimises picture and "
     "sound for each scene. 4K 144Hz panel with NVIDIA G-Sync, AMD FreeSync Premium, "
     "and four HDMI 2.1 ports make it perfect for gaming. Dolby Vision IQ and Dolby Atmos. "
     "webOS 24 with Magic Remote. Gallery mode for art display.",
     "LG OLED C4 55 inch 4K smart TV"),

    (389, 'ELEC-BOSE-QC45-068', 399.99, 0.13, 0.42, 100,
     "Bose QuietComfort 45 Bluetooth Wireless Noise Cancelling Headphones, White Smoke",
     "Bose QuietComfort 45 Bluetooth Noise Cancelling Headphones",
     "Bose QuietComfort 45 headphones deliver world-class noise cancellation and balanced "
     "audio. Switch seamlessly between Quiet Mode for full noise cancelling and Aware Mode "
     "to hear your surroundings. Up to 24 hours battery life on a single charge. "
     "2.5 hours of use from just 15 minutes of charging. Soft, cushioned ear cups and "
     "padded headband for all-day comfort. Simple multipoint pairing connects to two "
     "Bluetooth devices simultaneously.",
     "Bose QuietComfort 45 wireless headphones"),

    (390, 'ELEC-JBL-CHG5-069', 249.99, 0.14, 0.43, 130,
     "JBL Charge 5 Portable Waterproof Bluetooth Speaker with Powerbank",
     "JBL Charge 5 Portable Waterproof Bluetooth Speaker",
     "JBL Charge 5 delivers powerful JBL Pro Sound with a bold new design. IP67 waterproof "
     "and dustproof for adventures anywhere. The massive 7500mAh battery provides 20 hours "
     "of playtime and doubles as a power bank to charge your devices. "
     "PartyBoost lets you link multiple JBL speakers together. "
     "JBL Portable app gives you access to extra features. "
     "USB-C charging and integrated loop for easy carrying.",
     "JBL Charge 5 portable waterproof speaker"),

    (391, 'ELEC-ANKR-737PB-070', 129.99, 0.15, 0.44, 160,
     "Anker 737 Power Bank 24000mAh, 140W Max Output, 3-Port",
     "Anker 737 Power Bank 24000mAh 140W",
     "Anker 737 Power Bank packs 24000mAh capacity with 140W max output for rapid charging. "
     "The smart digital display shows exact battery percentage, input/output wattage, and "
     "estimated time to full charge or recharge. Three ports: two USB-C and one USB-A. "
     "Charge a MacBook Pro at full speed, a phone, and a tablet simultaneously. "
     "Compatible with Apple MagSafe, USB-C laptops, and all USB devices. "
     "Recharges from 0-100% in 1.5 hours.",
     "Anker 737 power bank 24000mAh 140W"),

    (392, 'ELEC-BLKN-3IN1WC-071', 59.99, 0.16, 0.44, 280,
     "Belkin BOOST CHARGE PRO 3-in-1 Wireless Charging Pad for Apple Devices",
     "Belkin 3-in-1 Wireless Charging Pad MagSafe Apple",
     "Belkin BOOST CHARGE PRO 3-in-1 Wireless Charging Pad charges iPhone with MagSafe "
     "at up to 15W, Apple Watch at up to 5W, and AirPods simultaneously. The flexible "
     "pad positions devices perfectly for efficient charging. MFi-certified by Apple "
     "for guaranteed compatibility. Non-slip surface keeps devices secure. "
     "Includes 30W power supply. Works with iPhone 15/14/13/12 series with MagSafe.",
     "Belkin 3-in-1 MagSafe wireless charging pad"),

    (393, 'ELEC-SAND-1TBPSSD-072', 189.99, 0.14, 0.43, 140,
     "SanDisk 1TB Extreme Pro Portable SSD, USB-C, 2000MB/s Read",
     "SanDisk 1TB Extreme Pro Portable SSD USB-C 2000MBs",
     "SanDisk Extreme Pro Portable SSD delivers blazing-fast transfer speeds up to 2000MB/s "
     "read and 2000MB/s write with USB 3.2 Gen 2x2. IP55 rated for water and dust resistance. "
     "Durable forged aluminum unibody construction withstands drops. "
     "256-bit AES hardware encryption with password protection. "
     "1TB capacity stores 200,000 photos or 30 hours of 4K video. "
     "Works with Mac, PC, Android, PS5, and Xbox.",
     "SanDisk 1TB Extreme Pro portable SSD"),

    (394, 'ELEC-SGTE-4TBHDD-073', 139.99, 0.15, 0.44, 175,
     "Seagate Expansion 4TB Portable External Hard Drive, USB 3.0",
     "Seagate Expansion 4TB Portable External Hard Drive USB 3.0",
     "Seagate Expansion 4TB Portable Hard Drive provides instant storage expansion for "
     "your computer. Plug-and-play setup requires no separate power supply — just connect "
     "via USB 3.0 and start saving files immediately. Stores up to 1 million photos, "
     "2,500 hours of video, or 250,000 songs. Compact size fits in a shirt pocket. "
     "Compatible with Windows and Mac. Includes a 3-year limited warranty.",
     "Seagate Expansion 4TB portable external hard drive"),

    (395, 'ELEC-LOGI-MXKS-074', 149.99, 0.15, 0.44, 155,
     "Logitech MX Keys S Wireless Illuminated Keyboard, Graphite",
     "Logitech MX Keys S Wireless Illuminated Keyboard Graphite",
     "Logitech MX Keys S features spherically dished keys that perfectly cradle your "
     "fingertips for a precise, comfortable typing experience. Smart Backlighting adjusts "
     "based on ambient light and proximity. Connect to up to three devices and switch "
     "instantly with Easy-Switch keys. Compatible with Windows, macOS, iPadOS, iOS, "
     "and Android. Rechargeable battery lasts up to 10 days with backlighting on. "
     "USB-C charging.",
     "Logitech MX Keys S wireless keyboard"),

    (396, 'ELEC-LOGI-G502XP-075', 199.99, 0.14, 0.43, 130,
     "Logitech G502 X PLUS Wireless Gaming Mouse, Black",
     "Logitech G502 X PLUS Wireless Gaming Mouse Black",
     "Logitech G502 X PLUS wireless gaming mouse features the LIGHTFORCE hybrid optical-"
     "mechanical switches for 68M clicks lifespan and virtually no click latency. "
     "HERO 25K sensor with zero smoothing, filtering, or acceleration up to 25,600 DPI. "
     "LIGHTSPEED wireless with 130-hour battery life. 13 programmable buttons. "
     "Adjustable weight system for personalised balance. "
     "LIGHTSYNC RGB lighting. POWERPLAY wireless charging compatible.",
     "Logitech G502 X Plus wireless gaming mouse"),

    (397, 'ELEC-SAMS-T7SH2-076', 249.99, 0.14, 0.43, 120,
     "Samsung T7 Shield 2TB Portable SSD, Rugged, USB 3.2",
     "Samsung T7 Shield 2TB Portable SSD Rugged",
     "Samsung T7 Shield portable SSD features a rugged beige exterior with a dynamic "
     "textured pattern inspired by nature's natural shapes. IP65 rated for dust and water "
     "resistance. Withstands drops up to 3 meters. Transfers up to 1,050MB/s with USB 3.2 "
     "Gen 2 (10Gbps). AES 256-bit hardware encryption. Works with PC, Mac, Android, "
     "PS5, and Xbox Series X/S. 2TB fits extensive video libraries and creative projects.",
     "Samsung T7 Shield 2TB portable SSD rugged"),

    (398, 'ELEC-APPL-MAGKB-077', 149.00, 0.14, 0.43, 200,
     "Apple Magic Keyboard with Touch ID for Mac with Apple Silicon, US English",
     "Apple Magic Keyboard Touch ID for Mac",
     "Apple Magic Keyboard with Touch ID features a comfortable, full-size keyboard with "
     "a built-in fingerprint reader for fast, secure authentication and Apple Pay purchases. "
     "Numeric keypad with document navigation controls and full-size arrow keys. "
     "Pairs automatically with your Mac via Bluetooth. Rechargeable battery lasts "
     "about a month or more. Lightning connector for charging and pairing. "
     "Compatible with Mac computers with Apple Silicon or T2 chip.",
     "Apple Magic Keyboard Touch ID for Mac"),

    (399, 'ELEC-CORS-K70RGB-078', 199.99, 0.14, 0.43, 110,
     "Corsair K70 RGB PRO Mechanical Gaming Keyboard, Cherry MX Red",
     "Corsair K70 RGB PRO Mechanical Gaming Keyboard Cherry MX Red",
     "Corsair K70 RGB PRO features Cherry MX Red mechanical switches for smooth, linear "
     "keystrokes ideal for competitive gaming. Per-key RGB backlighting with 16.8 million "
     "colours and dynamic lighting effects. Double-shot PBT keycaps for lasting durability. "
     "8MB of onboard storage for up to 50 profiles. Dual USB 2.0 passthrough port. "
     "Detachable soft-touch wrist rest. N-Key rollover for anti-ghosting. "
     "Adjustable tilt-leg positions.",
     "Corsair K70 RGB PRO mechanical gaming keyboard Cherry MX"),

    (400, 'ELEC-RAZR-DAV3HS-079', 179.99, 0.14, 0.43, 115,
     "Razer DeathAdder V3 HyperSpeed Wireless Gaming Mouse",
     "Razer DeathAdder V3 HyperSpeed Wireless Gaming Mouse",
     "Razer DeathAdder V3 HyperSpeed features the iconic ergonomic right-handed design "
     "with the 26K DPI Focus Pro optical sensor for pixel-perfect precision. HyperSpeed "
     "wireless technology at 4x the speed of regular Bluetooth. Ultra-lightweight "
     "construction at just 64g with a new speedflex cable design. "
     "90-hour battery life. Razer optical mouse switches rated for 90 million clicks. "
     "Compatible with HyperPolling Wireless Dongle for 8000Hz polling rate.",
     "Razer DeathAdder V3 HyperSpeed wireless gaming mouse"),

    (401, 'ELEC-ELGT-STDK-080', 249.99, 0.13, 0.42, 95,
     "Elgato Stream Deck MK.2, 15 Customizable LCD Keys, Live Production Controller",
     "Elgato Stream Deck MK2 15 LCD Keys Studio Controller",
     "Elgato Stream Deck MK.2 puts 15 customizable LCD keys at your fingertips to control "
     "your stream, content, and workflow. Trigger actions in OBS, Twitch, YouTube, Twitter, "
     "Spotify, and hundreds of other apps with a single touch. Create macros to automate "
     "complex tasks. Instantly switch scenes, launch media, adjust audio, and more. "
     "Detachable USB-C cable and adjustable tilt stand. "
     "Plugin marketplace with hundreds of integrations.",
     "Elgato Stream Deck MK2 15 key studio controller"),

    (402, 'ELEC-BLUE-YETI-081', 169.99, 0.14, 0.43, 140,
     "Blue Yeti USB Microphone for PC, Mac, Gaming, Recording, Streaming, Podcasting",
     "Blue Yeti USB Microphone Recording Streaming",
     "Blue Yeti is the world's most popular USB microphone, used by podcasters, streamers, "
     "musicians, and YouTubers worldwide. Three-capsule array with four pickup patterns "
     "(cardioid, bidirectional, omnidirectional, stereo) for any recording situation. "
     "Plug-and-play USB connectivity — no drivers needed. Built-in headphone amp for "
     "zero-latency monitoring. Gain control, mute button, and headphone volume knob. "
     "Compatible with Windows and Mac.",
     "Blue Yeti USB microphone streaming podcasting"),

    (403, 'ELEC-LOGI-C920S-082', 129.99, 0.15, 0.44, 165,
     "Logitech C920s HD Pro Webcam, 1080p/30fps, with Privacy Shutter",
     "Logitech C920s HD Pro Webcam 1080p Privacy Shutter",
     "Logitech C920s HD Pro Webcam delivers full 1080p video calling at 30fps for crisp, "
     "professional-quality video. Dual stereo microphones with noise reduction capture "
     "natural sound. Automatic HD light correction optimizes image quality in any lighting. "
     "Privacy shutter covers the lens when not in use. Works with Zoom, Microsoft Teams, "
     "Google Meet, Skype, and more. Universal clip fits laptops, monitors, and tripods. "
     "USB plug-and-play.",
     "Logitech C920s HD Pro webcam 1080p"),

    (404, 'ELEC-SAMS-G9OLED-083', 2199.99, 0.10, 0.38, 25,
     "Samsung 49-Inch Odyssey OLED G9 Curved Gaming Monitor, 240Hz, 0.03ms",
     "Samsung 49-Inch Odyssey OLED G9 Curved Gaming Monitor 240Hz",
     "Samsung 49-inch Odyssey OLED G9 gaming monitor features a massive DQHD (5120x1440) "
     "resolution across a 32:9 super ultrawide curved OLED panel. 240Hz refresh rate and "
     "0.03ms GTG response time for fluid, responsive gaming. DisplayHDR True Black 400. "
     "Quantum Dot OLED technology delivers vivid colours with perfect blacks. "
     "AMD FreeSync Premium Pro and NVIDIA G-Sync compatible. "
     "Gaming Hub for streaming games without a PC.",
     "Samsung 49 inch Odyssey OLED G9 curved gaming monitor"),

    (405, 'ELEC-LG-27GP950-084', 999.99, 0.12, 0.41, 40,
     "LG UltraGear 27GP950-B 27-Inch 4K UHD Nano IPS Gaming Monitor, 144Hz, 1ms",
     "LG UltraGear 27GP950-B 27-Inch 4K Nano IPS Gaming Monitor 144Hz",
     "LG UltraGear 27GP950-B features a 27-inch 4K UHD Nano IPS display with 144Hz refresh "
     "rate and 1ms (GtG) response time for ultra-smooth, blur-free gaming. NVIDIA G-Sync "
     "Compatible and AMD FreeSync Premium Pro. 98% DCI-P3 colour coverage for stunning "
     "HDR gaming. DisplayHDR 600 certified. Factory calibrated for Delta E < 2. "
     "USB-C with 90W power delivery. Three USB 3.0 downstream ports. "
     "Tilt, height, and pivot adjustable stand.",
     "LG UltraGear 27GP950 27 inch 4K gaming monitor 144Hz"),

    (406, 'ELEC-ASUS-PG279QM-085', 1199.99, 0.12, 0.41, 30,
     "ASUS ROG Swift PG279QM 27-Inch QHD IPS Gaming Monitor, 240Hz, G-Sync",
     "ASUS ROG Swift PG279QM 27-Inch 1440p 240Hz Gaming Monitor G-Sync",
     "ASUS ROG Swift PG279QM features a 27-inch WQHD (2560x1440) IPS display with a "
     "blazing 240Hz refresh rate and 1ms GTG response time. NVIDIA G-Sync for seamlessly "
     "smooth gameplay with no tearing or stuttering. 99% sRGB and 90% DCI-P3 colour "
     "coverage for vivid, accurate colours. ELMB SYNC allows motion blur reduction and "
     "G-Sync simultaneously. Adjustable stand with tilt, swivel, pivot, and height adjustment. "
     "Aura Sync RGB.",
     "ASUS ROG Swift PG279QM 27 inch 1440p 240Hz gaming monitor"),

    (407, 'ELEC-KING-FRYB32-086', 199.99, 0.14, 0.43, 120,
     "Kingston Fury Beast 32GB DDR5 5200MHz Desktop RAM Kit (2x16GB)",
     "Kingston Fury Beast 32GB DDR5 5200MHz RAM Kit 2x16GB",
     "Kingston Fury Beast DDR5 RAM delivers high-frequency performance for next-generation "
     "platforms. 32GB kit (2x16GB) at 5200MHz with XMP 3.0 and EXPO support for easy "
     "one-click overclocking. On-Die ECC helps correct errors to maintain data integrity. "
     "Aggressive low-profile spreader design for compatibility with large CPU coolers. "
     "Intel XMP 3.0 and AMD EXPO certified. Compatible with Intel Core 12th/13th/14th "
     "Gen and AMD Ryzen 7000 series platforms.",
     "Kingston Fury Beast 32GB DDR5 5200MHz RAM kit"),

    (408, 'ELEC-WDB-SN850X-087', 329.99, 0.13, 0.42, 105,
     "WD_BLACK 2TB SN850X M.2 NVMe SSD, PCIe Gen 4, 7300MB/s Read",
     "WD BLACK 2TB SN850X M.2 NVMe SSD PCIe Gen 4",
     "WD_BLACK SN850X NVMe SSD delivers the performance gamers need with sequential read "
     "speeds up to 7,300MB/s and sequential write speeds up to 6,600MB/s. PCIe Gen 4 "
     "interface for maximum compatibility with latest Intel and AMD platforms. "
     "Game Mode 2.0 adapts in real time to deliver faster game loading and reduced stutters. "
     "2TB capacity for storing large game libraries. Compatible with PlayStation 5. "
     "3D TLC NAND. 5-year limited warranty.",
     "WD Black 2TB SN850X M.2 NVMe SSD PCIe Gen 4"),

    (409, 'ELEC-SAMS-990P2T-088', 299.99, 0.13, 0.42, 115,
     "Samsung 990 PRO 2TB PCIe 4.0 NVMe M.2 Internal SSD",
     "Samsung 990 PRO 2TB PCIe 4.0 NVMe M.2 SSD",
     "Samsung 990 PRO NVMe SSD delivers sequential read speeds up to 7,450MB/s and write "
     "speeds up to 6,900MB/s for exceptional performance. PCIe 4.0 NVMe interface. "
     "Dynamic Thermal Guard maintains optimal operating temperature during intense use. "
     "Nickel-coated controller and heat spreader label for thermal management. "
     "Compatible with PS5. Samsung Magician software for easy management. "
     "V-NAND 3-bit MLC TLC. 5-year limited warranty.",
     "Samsung 990 PRO 2TB PCIe 4.0 NVMe M.2 SSD"),

    (410, 'ELEC-NGTR-AXE780-089', 549.99, 0.13, 0.42, 70,
     "NETGEAR Nighthawk AXE7800 Tri-Band Wi-Fi 6E Router (RAX78)",
     "NETGEAR Nighthawk AXE7800 Wi-Fi 6E Router",
     "NETGEAR Nighthawk AXE7800 is a tri-band Wi-Fi 6E router with 7,800Mbps total "
     "throughput (1,200+2,400+4,800Mbps). The 6GHz band provides a clean wireless lane "
     "for the latest Wi-Fi 6E devices with less interference. Covers up to 2,500 sq ft "
     "with up to 40 devices simultaneously. 4 high-gain antennas plus Beamforming+ for "
     "targeted range. Multi-Gig WAN/LAN ports. NETGEAR Armor cybersecurity powered by Bitdefender.",
     "NETGEAR Nighthawk AXE7800 Wi-Fi 6E router"),

    (411, 'ELEC-TPLK-DECOXE75-090', 699.99, 0.12, 0.41, 60,
     "TP-Link Deco XE75 Pro Wi-Fi 6E Mesh System, 3-Pack, AXE5400",
     "TP-Link Deco XE75 Pro Wi-Fi 6E Mesh System 3-Pack",
     "TP-Link Deco XE75 Pro delivers whole-home Wi-Fi 6E coverage with a dedicated 6GHz "
     "backhaul for maximum performance. AXE5400 tri-band system provides speeds up to "
     "5,400Mbps across 7,200 sq ft with 3 units. Connects up to 200 devices. "
     "Powered by a powerful 1.7GHz quad-core processor. WPA3 security and HomeShield "
     "for advanced network protection. Works with Alexa. Easy Deco app setup. "
     "2.5G WAN/LAN port on each unit.",
     "TP-Link Deco XE75 Pro Wi-Fi 6E mesh system 3 pack"),

    (412, 'ELEC-ROKU-ULTRA-091', 119.99, 0.15, 0.44, 195,
     "Roku Ultra 4K Streaming Device with Dolby Vision, Dolby Atmos, Voice Remote Pro",
     "Roku Ultra 4K Streaming Device Voice Remote Pro",
     "Roku Ultra is Roku's most powerful streaming device with 4K, Dolby Vision, and "
     "HDR10+ for the best picture quality. Dolby Atmos pass-through for immersive cinema "
     "audio. Voice Remote Pro with hands-free voice controls, TV controls, and a private "
     "listening mode with lost remote finder. Dual-band Wi-Fi for smooth streaming. "
     "Access 500+ streaming channels including Netflix, Disney+, and Prime Video. "
     "USB port for local media playback.",
     "Roku Ultra 4K streaming device Dolby Vision"),

    (413, 'ELEC-GOOG-CCGTV-092', 79.99, 0.16, 0.44, 220,
     "Google Chromecast with Google TV (4K), Snow",
     "Google Chromecast with Google TV 4K Snow",
     "Chromecast with Google TV (4K) streams in 4K HDR with Dolby Vision and HDR10+ "
     "support. Google TV organizes content from your streaming services into one place "
     "with personalized recommendations. Built-in Google Assistant lets you search "
     "across apps, control smart home devices, and more. Simple voice remote with "
     "dedicated Netflix and YouTube buttons. Dual-band Wi-Fi. HDMI connection. "
     "Compatible with Stadia, Disney+, Netflix, and YouTube TV.",
     "Google Chromecast with Google TV 4K"),

    (414, 'ELEC-RING-VDB4-093', 199.99, 0.14, 0.43, 145,
     "Ring Video Doorbell 4, Improved Motion Detection, Battery-Powered",
     "Ring Video Doorbell 4 Battery-Powered",
     "Ring Video Doorbell 4 features Pre-Roll video that captures up to 4 extra seconds "
     "of video before motion is detected so you never miss a moment. 1080p HD video with "
     "colour night vision and Live View on-demand monitoring. Advanced motion detection "
     "with customizable zones. Two-way talk with noise cancellation. "
     "Easy DIY installation — hardwired or battery-powered. "
     "Works with Amazon Alexa for voice control. Requires Ring Protect subscription for cloud recording.",
     "Ring Video Doorbell 4 battery-powered"),

    (415, 'ELEC-GOOG-NCAM-094', 149.99, 0.14, 0.43, 160,
     "Google Nest Cam Indoor Wired Security Camera",
     "Google Nest Cam Indoor Wired Security Camera",
     "Google Nest Cam (indoor, wired) delivers sharp 1080p HD video with HDR and night "
     "vision for clear footage day and night. Familiar face alerts notify you when "
     "recognized people are detected (Nest Aware required). Activity zones let you focus "
     "on the most important areas. Two-way audio for communicating through the camera. "
     "Works with Google Home and Amazon Alexa. Magnetic stand rotates 360 degrees. "
     "Requires a Nest Aware subscription for continuous recording.",
     "Google Nest Cam indoor wired security camera"),

    (416, 'ELEC-AMZN-KPWSE-095', 249.99, 0.13, 0.42, 175,
     "Kindle Paperwhite Signature Edition 32GB, 6.8-Inch, Auto-Adjusting Front Light",
     "Kindle Paperwhite Signature Edition 32GB 6.8-Inch",
     "Kindle Paperwhite Signature Edition features a 6.8-inch glare-free display with "
     "300 PPI for crisp, paper-like reading. Auto-adjusting front light adapts to your "
     "environment. 32GB storage holds thousands of books. Wireless charging support with "
     "included USB-C cable. Adjustable warm light to shift screen shade from white to amber. "
     "Up to 12 weeks battery life. IPX8 waterproof rating — safe to read in the bath "
     "or by the pool. Thin and light at just 188g.",
     "Kindle Paperwhite Signature Edition 32GB"),

    (417, 'ELEC-SONY-BRAVIA7-096', 2799.99, 0.10, 0.38, 22,
     "Sony BRAVIA 7 65-Inch Mini LED 4K HDR Google TV (2024)",
     "Sony BRAVIA 7 65-Inch Mini LED 4K Google TV 2024",
     "Sony BRAVIA 7 uses Mini LED backlighting with XR Backlight Master Drive for precise "
     "local dimming across thousands of zones. XR Processor delivers cognitive intelligence "
     "that processes thousands of elements simultaneously for lifelike picture and sound. "
     "Bravia Acoustic Multi-Audio positions sound to match the image on screen. "
     "Google TV platform with hands-free voice search. HDMI 2.1, VRR, ALLM for gaming. "
     "Bravia Core streaming service included.",
     "Sony BRAVIA 7 65 inch Mini LED 4K Google TV 2024"),

    (418, 'ELEC-EPSON-ET4850-097', 599.99, 0.13, 0.42, 80,
     "Epson EcoTank ET-4850 All-in-One Supertank Printer",
     "Epson EcoTank ET-4850 All-in-One Supertank Printer",
     "Epson EcoTank ET-4850 eliminates the frustration and cost of ink cartridges with "
     "supersized, easy-to-fill ink tanks. Includes enough ink for up to 2 years and "
     "7,500 pages in black or 6,000 pages in colour. Print, copy, scan, and fax wirelessly. "
     "2.4-inch colour touchscreen for easy navigation. Automatic 2-sided printing. "
     "50-sheet ADF for multi-page scanning. Voice-activated printing with Amazon Alexa "
     "and Google Assistant. Ethernet, USB, and USB flash drive connectivity.",
     "Epson EcoTank ET-4850 supertank all-in-one printer"),

    (419, 'ELEC-HP-LJ4101-098', 699.99, 0.12, 0.41, 65,
     "HP LaserJet Pro MFP 4101fdw Wireless Monochrome Laser Printer",
     "HP LaserJet Pro MFP 4101fdw Wireless Monochrome Printer",
     "HP LaserJet Pro MFP 4101fdw delivers fast, professional monochrome printing at up to "
     "40 pages per minute. Print, scan, copy, and fax wirelessly from anywhere. "
     "150-sheet ADF handles multi-page scan and copy jobs. Automatic 2-sided printing "
     "saves paper. 3.5-inch colour touchscreen makes navigation simple. "
     "HP Wolf Pro Security features to help keep data safe. "
     "Gigabit Ethernet, dual-band Wi-Fi, USB 2.0, and Bluetooth connectivity.",
     "HP LaserJet Pro MFP 4101fdw wireless monochrome printer"),

    (420, 'ELEC-BOSE-SB600-099', 649.99, 0.12, 0.41, 55,
     "Bose Smart Soundbar 600 with Dolby Atmos and Spatial Audio, Bluetooth",
     "Bose Smart Soundbar 600 Dolby Atmos Bluetooth",
     "Bose Smart Soundbar 600 delivers premium sound with TrueSpace Stereo technology "
     "and Dolby Atmos for an immersive three-dimensional audio experience. QuietPort "
     "technology controls distortion for clear, deep bass. Dirac Opteo room correction "
     "calibrates the sound to your room. Voice control with Amazon Alexa and Google "
     "Assistant built-in. Bose Music app for easy setup and control. "
     "HDMI eARC, optical audio, and Bluetooth connectivity. Wi-Fi and AirPlay 2.",
     "Bose Smart Soundbar 600 Dolby Atmos"),

    (421, 'ELEC-SONY-PSHBTV-100', 299.99, 0.13, 0.42, 85,
     "Sony HT-S400 2.1ch Soundbar with Powerful Wireless Subwoofer",
     "Sony HT-S400 2.1ch Soundbar Wireless Subwoofer",
     "Sony HT-S400 2.1ch soundbar with wireless subwoofer delivers powerful, room-filling "
     "sound with deep, impactful bass. S-Force PRO Front Surround creates a wide virtual "
     "surround sound experience from just two front channels. Bluetooth streaming from "
     "your smartphone. HDMI ARC for single cable connection to your TV. "
     "Optical input for compatibility with older TVs. "
     "Night mode reduces loud sounds and boosts quiet dialogue. "
     "Easy one-touch NFC connection for Android devices.",
     "Sony HT-S400 2.1ch soundbar wireless subwoofer"),
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
    w('-- INSERT 50 best-selling Electronics products (batch 2) + pricing + images')
    w(f'-- Generated: {NOW[:10]}')
    w('-- Products  : 50 rows  (product_number 372-421)')
    w('-- Pricing   : 150 rows (Retail + Promo + Wholesale per product)')
    w('-- Images    : 250 rows (5 images per product)')
    w('-- Category  : Electronics  (c3c5c4b0-3ef1-4540-90e2-65e7e2800bf0)')
    w('-- Currency  : CAD')
    w('-- ============================================================')
    w()

    # SECTION 1 — products
    cur.execute("""
        SELECT p.product_id, p.product_number, p.product_name, p.sku, p.description,
               p.category_id, p.currency_code, p.stock_quantity,
               p.is_active, p.is_synthetic, p.created_at, p.updated_at
        FROM products p
        JOIN category c ON p.category_id = c.category_id
        WHERE c.category_name = 'Electronics' AND p.product_number BETWEEN 372 AND 421
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

    # SECTION 2 — product_pricing
    cur.execute("""
        SELECT pp.product_pricing_id, pp.product_id, p.sku, p.product_number,
               pp.price_type, pp.price_value, pp.currency_code,
               pp.is_synthetic, pp.created_at, pp.updated_at
        FROM product_pricing pp
        JOIN products p ON pp.product_id = p.product_id
        WHERE p.product_number BETWEEN 372 AND 421
        ORDER BY p.product_number,
                 CASE pp.price_type WHEN 'Retail' THEN 1 WHEN 'Promo' THEN 2 ELSE 3 END
    """)
    pricing = cur.fetchall()
    w()
    w('-- ============================================================')
    w(f'-- SECTION 2: product_pricing ({len(pricing)} rows)')
    w('-- ============================================================')
    w()
    w('DELETE FROM product_pricing')
    w('WHERE product_id IN (')
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 372 AND 421')
    w(');')
    w()
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
        w(f'   {isy_s}, {esc(cr_s)}, {esc(up_s)});')
        w()

    # SECTION 3 — product_image
    cur.execute("""
        SELECT pi.product_image_id, pi.product_id, p.sku, p.product_number,
               pi.image_url, pi.sort_order, pi.alt_text, pi.created_at
        FROM product_image pi
        JOIN products p ON pi.product_id = p.product_id
        WHERE p.product_number BETWEEN 372 AND 421
        ORDER BY p.product_number, pi.sort_order
    """)
    images = cur.fetchall()
    w()
    w('-- ============================================================')
    w(f'-- SECTION 3: product_image ({len(images)} rows)')
    w('-- ============================================================')
    w()
    w('DELETE FROM product_image')
    w('WHERE product_id IN (')
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 372 AND 421')
    w(');')
    w()
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
    print(f'\nSQL saved → {SQL_OUT}')
    print(f'  Products: {len(products)}  Pricing: {len(pricing)}  Images: {len(images)}')


# ── DB insert ──────────────────────────────────────────────────────────────────

def db_insert(conn, prod_num, sku, name, desc, retail, ws_pct, promo_ratio, stock, img_urls, folder_enc):
    cur = conn.cursor()
    cat_dir = "Electronics"
    product_id = str(uuid.uuid4())

    ws    = round(retail * (1 - ws_pct), 2)
    promo = round(retail - (retail - ws) * promo_ratio, 2)

    cur.execute("""
        INSERT INTO products
          (product_id, product_number, product_name, sku, description,
           category_id, currency_code, stock_quantity, is_active, is_synthetic,
           created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,'CAD',%s,TRUE,FALSE,NOW(),NOW())
        ON CONFLICT (sku) DO UPDATE SET
          product_name   = EXCLUDED.product_name,
          description    = EXCLUDED.description,
          stock_quantity = EXCLUDED.stock_quantity,
          updated_at     = NOW()
        RETURNING product_id
    """, (product_id, prod_num, name, sku, desc, ELEC_CAT_ID, stock))
    row = cur.fetchone()
    product_id = str(row[0])

    for ptype, pval in [('Retail', retail), ('Promo', promo), ('Wholesale', ws)]:
        cur.execute("""
            INSERT INTO product_pricing
              (product_pricing_id, product_id, price_type, price_value, currency_code,
               is_synthetic, created_at, updated_at)
            VALUES (%s,%s,%s,%s,'CAD',FALSE,NOW(),NOW())
        """, (str(uuid.uuid4()), product_id, ptype, pval))

    cur.execute("DELETE FROM product_image WHERE product_id = %s", (product_id,))
    for i, img_file in enumerate(img_urls, 1):
        db_url   = f"https://agentorc.ca/image/{quote(cat_dir, safe='')}/{folder_enc}/{img_file}"
        alt_text = f"{name} - Image {i}"
        cur.execute("""
            INSERT INTO product_image
              (product_image_id, product_id, image_url, sort_order, alt_text, created_at)
            VALUES (%s,%s,%s,%s,%s,NOW())
        """, (str(uuid.uuid4()), product_id, db_url, i, alt_text))

    conn.commit()
    return product_id, ws, promo


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    cat_dir    = "Electronics"
    local_cat  = os.path.join(IMAGE_BASE, cat_dir)
    remote_cat = f"{REMOTE_BASE}/{cat_dir}"

    os.makedirs(local_cat, exist_ok=True)
    mkdir_remote(REMOTE_BASE, cat_dir)

    conn    = psycopg2.connect(host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                               user=DB_USER, password=DB_PASS)
    session = make_session()

    print("Warming up Amazon.ca session...")
    fetch_page(session, "https://www.amazon.ca")
    sleep()

    succeeded = 0
    total_imgs = 0
    total_pricing = 0

    for (prod_num, sku, retail, ws_pct, promo_ratio, stock,
         name, folder_name, desc, query) in PRODUCTS:

        print(f"\n{'='*70}")
        print(f"[{prod_num}] {name}")

        folder     = sanitize_folder(folder_name)
        folder_enc = quote(folder, safe='')
        local_dir  = os.path.join(local_cat, folder)
        remote_dir = f"{remote_cat}/{folder}"   # unencoded — Apache decodes on serve

        os.makedirs(local_dir, exist_ok=True)

        # ── Step 1: Download images ──────────────────────────────────────────
        print(f"  Searching Amazon.ca: {query}")
        results = search_amazon(session, query)
        print(f"  Found {len(results)} candidates")
        sleep()

        downloaded = []
        tried = 0
        for result in results:
            if len(downloaded) >= IMAGES_PER:
                break
            if tried >= 4:
                break
            print(f"  Trying: {result['title'][:65]}")
            img_urls = get_product_images(session, result['url'])
            print(f"  Found {len(img_urls)} images")
            sleep()
            tried += 1
            for url in img_urls:
                if len(downloaded) >= IMAGES_PER:
                    break
                idx  = len(downloaded) + 1
                dest = os.path.join(local_dir, f"image_{idx}.jpg")
                if download_image(session, url, dest):
                    downloaded.append(dest)
                    print(f"    Downloaded {idx}/{IMAGES_PER}")
            if downloaded and len(downloaded) < IMAGES_PER:
                sleep()

        if not downloaded:
            print(f"  [SKIP] No images downloaded for {name}")
            continue

        print(f"  Total images: {len(downloaded)}")

        # ── Step 2: Upload to cPanel ─────────────────────────────────────────
        print(f"  Uploading to cPanel: {folder[:60]}")
        mkdir_remote(remote_cat, folder)
        existing = list_remote_files(remote_dir)

        up_ok = 0
        for local_path in downloaded:
            fname = os.path.basename(local_path)
            if existing.get(fname, 0) > 0:
                print(f"    [SKIP] {fname}")
                up_ok += 1
                continue
            ok = upload_file_cpanel(local_path, remote_dir)
            print(f"    [{'OK' if ok else 'FAIL'}] {fname}")
            if ok:
                up_ok += 1
                time.sleep(0.3)
        print(f"  Uploaded {up_ok}/{len(downloaded)}")

        # ── Step 3: DB insert ────────────────────────────────────────────────
        img_files_for_db = [os.path.basename(p) for p in downloaded]
        try:
            product_id, ws, promo = db_insert(
                conn, prod_num, sku, name, desc,
                retail, ws_pct, promo_ratio, stock,
                img_files_for_db, folder_enc
            )
            total_imgs    += len(downloaded)
            total_pricing += 3
            succeeded     += 1
            print(f"  DB OK  retail=${retail}  promo=${promo}  ws=${ws}  imgs={len(downloaded)}")
        except Exception as e:
            print(f"  [DB ERROR] {e}")
            conn.rollback()

    conn.close()

    # ── Step 4: Generate SQL ─────────────────────────────────────────────────
    generate_sql()

    print(f"\n{'='*70}")
    print(f"DONE.  Succeeded: {succeeded}/{len(PRODUCTS)}")
    print(f"       Images: {total_imgs}  Pricing rows: {total_pricing}")


if __name__ == "__main__":
    main()
