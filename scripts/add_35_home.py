"""
Add 35 best-selling Home Essentials products:
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally  → image/Home Essentials/{Folder Name}/image_N.jpg
  3. Uploads to agentorc.ca using UNENCODED folder names (spaces, not %20)
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)
  5. Generates sql/insert_35_home.sql from live DB data

Run from project root:
    python scripts/add_35_home.py
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
SQL_OUT      = r"D:\a\crm_agent\sql\insert_35_home.sql"
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

HOME_CAT_ID = "c346f439-e972-4f0a-8115-f3baa63cc1d8"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 35 Best-selling Home Essentials products ──────────────────────────────────
# (product_number, sku, retail_cad, ws_pct, promo_ratio, stock,
#  full_product_name, folder_name, description, amazon_search_query)
PRODUCTS = [
    (306, 'HOM-DAWN-DISH-001', 12.99, 0.18, 0.48, 520,
     "Dawn Platinum Dishwashing Liquid Soap, Fresh Scent, 1.07 L",
     "Dawn Platinum Dishwashing Liquid Fresh Scent 1.07L",
     "Dawn Platinum Dishwashing Liquid cuts through grease 4x faster than the leading "
     "bargain brand. Its concentrated formula means you use less with each wash, making "
     "this 1.07 L bottle go further. The fresh scent leaves your dishes smelling clean. "
     "Safe for use on all cookware and dishes. Tough on grease yet gentle on hands.",
     "Dawn Platinum dishwashing liquid fresh scent"),

    (307, 'HOM-TIDE-PODS-002', 29.99, 0.18, 0.48, 440,
     "Tide PODS Laundry Detergent, Spring Meadow, 81 Count",
     "Tide PODS Laundry Detergent Spring Meadow 81 Count",
     "Tide PODS are a 3-in-1 laundry solution combining detergent, stain remover, and "
     "brightener in one convenient pac. The pre-measured pods dissolve quickly in any "
     "water temperature and work in both HE and standard machines. Spring Meadow scent "
     "leaves clothes fresh and clean. 81-count value pack. No measuring, no mess.",
     "Tide PODS laundry detergent spring meadow 81 count"),

    (308, 'HOM-DOWNY-SOFT-003', 19.99, 0.18, 0.48, 390,
     "Downy Ultra Fabric Softener, April Fresh, 1.53 L",
     "Downy Ultra Fabric Softener April Fresh 1.53L",
     "Downy Ultra Fabric Softener conditions fibres to reduce wrinkles, static, and "
     "pilling while leaving clothes feeling soft and smelling fresh for up to 100 days. "
     "The April Fresh scent is a classic, clean fragrance loved by millions. This "
     "concentrated 1.53 L bottle provides 64 loads. Compatible with HE and standard "
     "washing machines. Safe for all fabrics.",
     "Downy Ultra fabric softener April Fresh 1.53L"),

    (309, 'HOM-GLAD-BAGS-004', 16.99, 0.18, 0.48, 470,
     "Glad ForceFlex Plus Large Garbage Bags, 90 L, 40 Count",
     "Glad ForceFlex Plus Large Garbage Bags 90L 40 Count",
     "Glad ForceFlex Plus garbage bags feature a unique diamond texture that stretches "
     "to fit more garbage without ripping or tearing. The leak-resistant bottom seal "
     "protects against drips and leaks. Each bag holds up to 90 litres. Fresh Clean scent "
     "neutralizes odours. 40-count box. Ideal for kitchen and household waste.",
     "Glad ForceFlex large garbage bags 90L"),

    (310, 'HOM-ZIPLK-BAGS-005', 13.99, 0.18, 0.50, 500,
     "Ziploc Double Zipper Freezer Bags, Gallon Size, 75 Count",
     "Ziploc Double Zipper Freezer Bags Gallon 75 Count",
     "Ziploc Double Zipper Freezer Bags feature a double seal for extra protection against "
     "freezer burn and moisture. The double-zipper design makes it easy to open and close "
     "securely. BPA-free. Each bag is reusable and dishwasher-safe. Gallon size is perfect "
     "for storing meats, vegetables, soups, and leftovers. 75-count value box.",
     "Ziploc double zipper freezer bags gallon 75 count"),

    (311, 'HOM-CLING-WRAP-006', 11.99, 0.18, 0.50, 480,
     "Saran Premium Wrap Plastic Cling Wrap, 300 ft Roll",
     "Saran Premium Wrap Plastic Cling Wrap 300ft",
     "Saran Premium Wrap clings tightly to bowls, plates, and food surfaces to create an "
     "airtight seal that keeps food fresh longer. The 300-foot roll provides long-lasting "
     "value. Easy-slide cutter makes cutting clean and simple. BPA-free. Microwave-safe "
     "for reheating. Ideal for wrapping sandwiches, covering leftovers, and food storage.",
     "Saran cling wrap plastic food wrap 300ft"),

    (312, 'HOM-WYND-AIRFR-007', 14.99, 0.18, 0.48, 350,
     "Febreze Air Freshener Spray, Linen & Sky, 3-Pack, 250g Each",
     "Febreze Air Freshener Spray Linen Sky 3-Pack",
     "Febreze Air Freshener eliminates odours rather than just masking them, using OdorClear "
     "technology to neutralize odour molecules on contact. Linen & Sky is a light, fresh "
     "scent reminiscent of clean laundry on a breezy day. This 3-pack provides exceptional "
     "value. Safe to use around children and pets when used as directed. Each can lasts for "
     "hundreds of sprays.",
     "Febreze air freshener spray linen sky 3 pack"),

    (313, 'HOM-SCOT-TISS-008', 18.99, 0.18, 0.48, 420,
     "Scotties Facial Tissue, Triple Layer, 6 Boxes x 126 Sheets",
     "Scotties Facial Tissue Triple Layer 6 Boxes 126 Sheets",
     "Scotties Triple Layer Facial Tissue provides extra softness and strength with three "
     "layers of tissue. Specially designed to be gentle on sensitive skin while being "
     "strong enough for everyday use. Each box contains 126 2-ply tissues. This 6-box "
     "multipack offers great value and ensures you always have tissues on hand. "
     "FSC-certified. Dermatologist tested.",
     "Scotties facial tissue triple layer 6 boxes"),

    (314, 'HOM-BOUNTY-PAPR-009', 22.99, 0.18, 0.48, 400,
     "Bounty Select-A-Size Paper Towels, 12 Double Rolls",
     "Bounty Select-A-Size Paper Towels 12 Double Rolls",
     "Bounty Select-A-Size Paper Towels let you choose the right size sheet for the job — "
     "full or half size. Each double roll is 2x longer than a regular roll. Bounty's "
     "durable, absorbent sheets soak up messes faster than the leading ordinary brand. "
     "12 double rolls = 24 regular rolls worth. 2-ply for strength and absorbency. "
     "Ideal for kitchens, bathrooms, and cleaning throughout the home.",
     "Bounty Select-A-Size paper towels 12 double rolls"),

    (315, 'HOM-CHAR-BATH-010', 24.99, 0.18, 0.48, 380,
     "Charmin Ultra Soft Toilet Paper, 24 Mega Rolls",
     "Charmin Ultra Soft Toilet Paper 24 Mega Rolls",
     "Charmin Ultra Soft Toilet Paper is softer and more absorbent than the leading "
     "bargain brand. Each mega roll is 4x longer than a regular roll, so you change "
     "the roll less often. 24 mega rolls = 96 regular rolls. 2-ply cushiony sheets "
     "are gentle on skin. Clog-safe and septic-safe when used as directed. "
     "The go-to choice for comfort and value.",
     "Charmin Ultra Soft toilet paper 24 mega rolls"),

    (316, 'HOM-LYSOL-SPRY-011', 17.99, 0.18, 0.48, 460,
     "Lysol Disinfectant Spray, Crisp Linen, 3 x 539 g",
     "Lysol Disinfectant Spray Crisp Linen 3 Pack 539g",
     "Lysol Disinfectant Spray kills 99.9% of viruses and bacteria on hard and soft "
     "surfaces, including the COVID-19 virus. Eliminates odours at the source rather "
     "than just masking them. Crisp Linen scent leaves surfaces smelling clean and fresh. "
     "Approved by Health Canada. This 3-pack value set covers kitchens, bathrooms, "
     "bedrooms, and living areas. No rinsing required on most surfaces.",
     "Lysol disinfectant spray crisp linen 3 pack"),

    (317, 'HOM-CLRX-WIPE-012', 14.99, 0.18, 0.48, 490,
     "Clorox Disinfecting Wipes, Fresh Scent + Citrus Blend, 225 Count",
     "Clorox Disinfecting Wipes Fresh Scent Citrus Blend 225 Count",
     "Clorox Disinfecting Wipes kill 99.9% of germs including bacteria and viruses on "
     "hard, non-porous surfaces. No rinsing required — just wipe and let air dry. "
     "This 225-count value pack includes two fresh scents: Fresh Scent and Citrus Blend. "
     "Each wipe is thick and durable for effective cleaning. Approved for use in kitchens "
     "and bathrooms. Safe on most sealed surfaces.",
     "Clorox disinfecting wipes fresh citrus 225 count"),

    (318, 'HOM-MRCLR-CLNR-013', 12.99, 0.18, 0.50, 430,
     "Mr. Clean Multi-Surface Cleaner, Summer Citrus, 2.63 L",
     "Mr Clean Multi-Surface Cleaner Summer Citrus 2.63L",
     "Mr. Clean Multi-Surface Liquid Cleaner cleans and deodorizes multiple surfaces "
     "including floors, walls, counters, and appliances. The Summer Citrus scent leaves "
     "a fresh, clean fragrance. This concentrated 2.63 L bottle dilutes with water for "
     "economical use on floors or can be used full-strength for tougher jobs. Cuts through "
     "grease and grime. No rinsing needed on most surfaces.",
     "Mr Clean multi-surface cleaner summer citrus 2.63L"),

    (319, 'HOM-PLEDG-WIPE-014', 11.99, 0.18, 0.50, 360,
     "Pledge Multi-Surface Furniture Spray, Orange Clean, 335 g",
     "Pledge Multi-Surface Furniture Spray Orange Clean 335g",
     "Pledge Multi-Surface Furniture Spray cleans, shines, and protects wood, leather, "
     "stainless steel, and plastic surfaces in one easy step. The Orange Clean formula "
     "cuts through grease and fingerprints while leaving a protective layer that repels "
     "dust. No wax build-up. Safe for use on finished wood, laminate, and most surfaces. "
     "Fresh citrus scent. 335 g aerosol can.",
     "Pledge furniture spray orange clean multi-surface"),

    (320, 'HOM-SCOTB-SCRU-015', 9.99, 0.18, 0.50, 550,
     "Scotch-Brite Heavy Duty Scrub Sponge, 9 Pack",
     "Scotch-Brite Heavy Duty Scrub Sponge 9 Pack",
     "Scotch-Brite Heavy Duty Scrub Sponges feature a tough, durable scrubbing side that "
     "removes stuck-on messes without scratching most non-coated cookware. The soft absorbent "
     "side wipes up spills and cleans delicate surfaces. Long-lasting and resistant to "
     "odour-causing bacteria growth. 9-pack value set. Ideal for pots, pans, dishes, "
     "counters, and sinks.",
     "Scotch-Brite heavy duty scrub sponge 9 pack"),

    (321, 'HOM-RUBB-GLVS-016', 13.99, 0.18, 0.50, 410,
     "Playtex Living Reusable Rubber Cleaning Gloves, Medium, 3-Pack",
     "Playtex Living Rubber Cleaning Gloves Medium 3-Pack",
     "Playtex Living Reusable Rubber Gloves protect hands from harsh chemicals, hot water, "
     "and dirt during household cleaning tasks. The cotton-flock lining makes them easy to "
     "put on and take off. Textured fingers and palm provide a secure grip even when wet. "
     "Medium size fits most hands. This 3-pack value set provides pairs for kitchen, "
     "bathroom, and outdoor use. Durable latex rubber construction.",
     "Playtex Living rubber cleaning gloves medium 3 pack"),

    (322, 'HOM-FBRZ-PLUG-017', 21.99, 0.18, 0.48, 320,
     "Febreze Plug Air Freshener Refill, Gain Original Scent, 4 Count",
     "Febreze Plug Air Freshener Refill Gain Original 4 Count",
     "Febreze Plug Air Freshener continuously eliminates odours and fills your home with "
     "the fresh scent of Gain Original. Each refill lasts up to 45 days on low setting. "
     "The plug-in device adjusts from low to high intensity. OdorClear technology neutralizes "
     "tough odours rather than covering them. This 4-refill pack provides up to 180 days "
     "of freshness. Safe to use around people and pets.",
     "Febreze PLUG air freshener refill Gain original 4 pack"),

    (323, 'HOM-DUCK-TAPE-018', 14.99, 0.18, 0.50, 370,
     "Duck Max Strength Duct Tape, Silver, 48mm x 27.4m",
     "Duck Max Strength Duct Tape Silver 48mm x 27.4m",
     "Duck Max Strength Duct Tape is the strongest in the Duck lineup with a 3-layer "
     "construction featuring a strong polyethylene backing, a robust reinforced fabric "
     "mesh, and a high-tack rubber adhesive. Sticks to rough, smooth, and uneven surfaces. "
     "Water-resistant and UV-resistant. 48 mm wide x 27.4 m long. Tears easily by hand. "
     "Ideal for repairs, bundling, sealing, and crafts.",
     "Duck duct tape silver max strength 48mm"),

    (324, 'HOM-ATLS-BATRY-019', 26.99, 0.18, 0.48, 430,
     "Energizer MAX AA Batteries, 24 Pack",
     "Energizer MAX AA Batteries 24 Pack",
     "Energizer MAX AA Batteries deliver long-lasting power for everyday devices including "
     "remotes, toys, clocks, flashlights, and wireless devices. They hold power in storage "
     "for up to 10 years so you always have batteries when you need them. Anti-leak "
     "construction protects devices from leakage damage. 24-pack value. "
     "Made with recycled materials. Backed by Energizer's quality guarantee.",
     "Energizer MAX AA batteries 24 pack"),

    (325, 'HOM-MAGC-ERAS-020', 12.99, 0.18, 0.50, 480,
     "Mr. Clean Magic Eraser Original, 8 Count",
     "Mr Clean Magic Eraser Original 8 Count",
     "Mr. Clean Magic Eraser is a versatile cleaning pad that removes tough messes from "
     "walls, baseboards, floors, bathtubs, and more with just water — no harsh scrubbing "
     "required. The micro-scrubbers inside reach into the surface texture to lift and "
     "remove dirt, grime, and scuffs. Works on most surfaces. This 8-count pack provides "
     "excellent value. Just wet, squeeze, and erase.",
     "Mr Clean Magic Eraser original cleaning pads 8 count"),

    (326, 'HOM-PINE-SOL-021', 11.99, 0.18, 0.50, 450,
     "Pine-Sol All Purpose Cleaner, Original Pine, 2.41 L",
     "Pine-Sol All Purpose Cleaner Original Pine 2.41L",
     "Pine-Sol All Purpose Cleaner is trusted to clean and disinfect multiple surfaces "
     "throughout the home. The original pine scent provides a fresh, clean fragrance after "
     "each use. Kills 99.9% of germs when used as directed. Effective on floors, counters, "
     "sinks, and appliances. This 2.41 L bottle is economical — dilute with water for "
     "regular cleaning or use full-strength for tough jobs.",
     "Pine-Sol all purpose cleaner original pine 2.41L"),

    (327, 'HOM-DRAN-UNCLG-022', 13.99, 0.18, 0.48, 340,
     "Drano Max Gel Clog Remover, 900 mL",
     "Drano Max Gel Clog Remover 900mL",
     "Drano Max Gel Clog Remover is a thick gel that sinks through standing water straight "
     "to the clog to dissolve hair, soap scum, and other blockages. Works in 15–30 minutes. "
     "Safe for all pipes including PVC, plastic, metal, and old pipes. Can be used in "
     "sinks, tubs, and showers. The powerful formula cuts through even the toughest clogs. "
     "900 mL bottle for multiple uses.",
     "Drano Max Gel clog remover drain cleaner 900ml"),

    (328, 'HOM-WDEX-GLASS-023', 9.99, 0.18, 0.50, 510,
     "Windex Original Glass Cleaner, 946 mL",
     "Windex Original Glass Cleaner 946mL",
     "Windex Original Glass Cleaner leaves windows, mirrors, and glass surfaces streak-free "
     "and sparkling clean. The ammonia-D formula cuts through fingerprints, smudges, and "
     "dust in one easy step. Dries quickly with no residue. Safe for use on glass, mirrors, "
     "windows, shower doors, and chrome surfaces. 946 mL bottle with trigger sprayer. "
     "The #1 glass cleaning brand trusted for decades.",
     "Windex original glass cleaner 946ml spray bottle"),

    (329, 'HOM-GLAD-PRESS-024', 15.99, 0.18, 0.48, 380,
     "Glad Press'n Seal Plastic Wrap, 70 sq ft, 3-Pack",
     "Glad PressN Seal Plastic Wrap 70sqft 3-Pack",
     "Glad Press'n Seal creates an airtight, leakproof seal on bowls, plates, and "
     "containers. The unique Griptex technology seals to more surfaces than regular plastic "
     "wrap — including plastic, glass, ceramic, and even skin. Each roll is 70 sq ft. "
     "This 3-pack provides 210 sq ft of versatile food wrap. Microwave-safe. "
     "BPA-free. Works on irregular shapes and containers without lids.",
     "Glad Press n Seal plastic wrap 70sqft 3 pack"),

    (330, 'HOM-OXCLN-PODR-025', 16.99, 0.18, 0.48, 400,
     "OxiClean Versatile Stain Remover Powder, 3 kg",
     "OxiClean Versatile Stain Remover Powder 3kg",
     "OxiClean Versatile Stain Remover harnesses the power of oxygen to break down and "
     "remove over 101 different types of stains including wine, coffee, grass, grease, "
     "and blood. Chlorine-free and colour-safe for use on laundry, carpets, hard surfaces, "
     "and outdoor furniture. Works in all water temperatures. This 3 kg value size "
     "provides hundreds of treatments. Safe for use in HE machines.",
     "OxiClean versatile stain remover powder 3kg"),

    (331, 'HOM-RNZP-BKSD-026', 21.99, 0.18, 0.48, 360,
     "Arm & Hammer Baking Soda, 4.5 kg",
     "Arm and Hammer Baking Soda 4.5kg",
     "Arm & Hammer Pure Baking Soda has hundreds of uses around the home: deodorizing "
     "fridges, cleaning surfaces, whitening teeth, baking, and neutralizing odours in "
     "carpets and upholstery. This large 4.5 kg bag is ideal for households that use "
     "baking soda regularly. 100% pure sodium bicarbonate with no additives. "
     "Naturally derived, biodegradable, and safe around children and pets.",
     "Arm and Hammer baking soda 4.5kg large bag"),

    (332, 'HOM-CSTCO-WRPG-027', 18.99, 0.18, 0.48, 410,
     "Reynolds Wrap Heavy Duty Aluminum Foil, 200 sq ft",
     "Reynolds Wrap Heavy Duty Aluminum Foil 200sqft",
     "Reynolds Wrap Heavy Duty Aluminum Foil is 50% thicker than standard foil for "
     "superior protection against punctures, tears, and freezer burn. Ideal for grilling, "
     "roasting, baking, and freezing. Creates a tight seal around food to lock in moisture "
     "and flavour. 200 sq ft roll provides long-lasting value. Safe for oven, grill, and "
     "freezer use. BPA-free.",
     "Reynolds Wrap heavy duty aluminum foil 200sqft"),

    (333, 'HOM-RUBB-MAID-028', 34.99, 0.18, 0.48, 240,
     "Rubbermaid Brilliance Food Storage Container Set, 22-Piece",
     "Rubbermaid Brilliance Food Storage Container Set 22-Piece",
     "Rubbermaid Brilliance containers feature 100% leak-proof lids with a secure latching "
     "system and crystal-clear Tritan plastic walls for easy content visibility. Stain and "
     "odour resistant. Microwave-safe with vented lids (remove seals), dishwasher-safe, "
     "and freezer-safe. Stackable design saves cabinet space. This 22-piece set includes "
     "multiple sizes for snacks, sides, and full meals. BPA-free.",
     "Rubbermaid Brilliance food storage container set 22 piece"),

    (334, 'HOM-GLAD-PRSS-029', 27.99, 0.18, 0.48, 290,
     "Glad GladWare Food Storage Containers, Various Sizes, 34-Piece",
     "Glad GladWare Food Storage Container Set 34-Piece",
     "Glad GladWare Food Storage Containers feature a Sure-Seal lid that clicks into place "
     "to prevent leaks and spills. Containers are reusable, microwave-safe, dishwasher-safe "
     "on the top rack, and stackable for organised storage. This 34-piece set includes "
     "multiple sizes from snack cups to entrée containers. BPA-free. Clear bottom for "
     "easy food identification.",
     "Glad GladWare food storage containers 34 piece set"),

    (335, 'HOM-SHRP-LITBULB-030', 22.99, 0.18, 0.48, 350,
     "Philips LED Light Bulbs A19 60W Equivalent, Soft White, 16-Pack",
     "Philips LED Light Bulbs A19 60W Soft White 16-Pack",
     "Philips LED A19 light bulbs use only 8.5 watts while delivering the same warm, soft "
     "white light as a 60W incandescent bulb. Lasts up to 10,000 hours — about 10 years "
     "of normal use. Dimmable. Instant-on with no warm-up time. Fits standard medium "
     "base (E26) fixtures. Energy Star certified. This 16-pack provides outstanding "
     "value and covers most rooms in the home. 800 lumens, 2700K colour temperature.",
     "Philips LED light bulbs A19 60W soft white 16 pack"),

    (336, 'HOM-IRBT-VACU-031', 699.99, 0.15, 0.45, 80,
     "iRobot Roomba i3+ EVO Self-Emptying Robot Vacuum",
     "iRobot Roomba i3 EVO Self-Emptying Robot Vacuum",
     "The iRobot Roomba i3+ EVO robot vacuum automatically empties its own bin into the "
     "Clean Base Automatic Dirt Disposal, holding up to 60 days of dirt, dust, and hair. "
     "Dual multi-surface rubber brushes adapt to different floor types. Works with Alexa "
     "and Google Assistant for voice control. 3-Stage Cleaning System targets dirt, dust, "
     "and pet hair. Smart mapping learns your home's floor plan. Compatible with iRobot OS.",
     "iRobot Roomba i3 self emptying robot vacuum"),

    (337, 'HOM-DSON-CORD-032', 399.99, 0.15, 0.45, 100,
     "Dyson V8 Cordless Stick Vacuum Cleaner",
     "Dyson V8 Cordless Stick Vacuum Cleaner",
     "The Dyson V8 cordless stick vacuum offers powerful suction in a lightweight, "
     "versatile design. Converts to a handheld vacuum for stairs, upholstery, and "
     "in-car cleaning. Up to 40 minutes of run time on a single charge. The Radial "
     "Cyclone technology captures microscopic dust and allergens. Hygienic bin emptying "
     "with one click. Includes multiple attachments for whole-home cleaning. "
     "HEPA-level filtration captures 99.97% of particles.",
     "Dyson V8 cordless stick vacuum cleaner"),

    (338, 'HOM-INSTPOT-DUO-033', 149.99, 0.16, 0.46, 150,
     "Instant Pot Duo 7-in-1 Electric Pressure Cooker, 6 Qt",
     "Instant Pot Duo 7-in-1 Electric Pressure Cooker 6 Qt",
     "The Instant Pot Duo is a 7-in-1 multi-use programmable pressure cooker: pressure "
     "cooker, slow cooker, rice cooker, sauté pan, steamer, yogurt maker, and food warmer. "
     "Cooks up to 70% faster than conventional cooking. 13 one-touch Smart Programs. "
     "Safety-tested with 10 safety mechanisms. 6-quart capacity feeds 4–6 people. "
     "Dishwasher-safe lid and inner pot. Stainless steel inner pot.",
     "Instant Pot Duo 7-in-1 electric pressure cooker 6 quart"),

    (339, 'HOM-KEURIG-K55-034', 169.99, 0.16, 0.46, 120,
     "Keurig K-Classic Coffee Maker, Single Serve K-Cup Pod Brewer",
     "Keurig K-Classic Coffee Maker Single Serve K-Cup Pod",
     "The Keurig K-Classic brews a perfect cup of coffee, tea, hot cocoa, or iced beverage "
     "in under a minute using K-Cup pods. Choose from three brew sizes: 6, 8, or 10 oz. "
     "The large 48 oz removable water reservoir allows you to brew multiple cups before "
     "refilling. Auto Off feature saves energy. Quiet Brew technology. Compatible with "
     "My K-Cup Universal Reusable Filter for ground coffee. Over 400 varieties of K-Cup pods.",
     "Keurig K-Classic coffee maker single serve K-Cup brewer"),

    (340, 'HOM-NEST-THRM-035', 219.99, 0.15, 0.45, 110,
     "Google Nest Learning Thermostat, 3rd Generation, Stainless Steel",
     "Google Nest Learning Thermostat 3rd Gen Stainless Steel",
     "The Google Nest Learning Thermostat programs itself based on your schedule and "
     "preferences, and turns itself down when you're away to save energy — typically "
     "saving 10–12% on heating and cooling costs. The large, easy-to-read display shows "
     "temperature, weather, and time. Compatible with most HVAC systems. Works with "
     "Google Home, Alexa, and Apple HomeKit. Easy DIY installation in about 30 minutes.",
     "Google Nest Learning Thermostat 3rd generation stainless steel"),
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
    w('-- INSERT 35 best-selling Home Essentials products + pricing + images')
    w(f'-- Generated: {NOW[:10]}')
    w('-- Products  : 35 rows  (product_number 306-340)')
    w('-- Pricing   : 105 rows (Retail + Promo + Wholesale per product)')
    w('-- Images    : 175 rows (5 images per product)')
    w('-- Category  : Home Essentials  (c346f439-e972-4f0a-8115-f3baa63cc1d8)')
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
        WHERE c.category_name = 'Home Essentials' AND p.product_number >= 306
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
        WHERE p.product_number BETWEEN 306 AND 340
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
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 306 AND 340')
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

    # SECTION 3 ── product_image
    cur.execute("""
        SELECT pi.product_image_id, pi.product_id, p.sku, p.product_number,
               pi.image_url, pi.sort_order, pi.alt_text, pi.created_at
        FROM product_image pi
        JOIN products p ON pi.product_id = p.product_id
        WHERE p.product_number BETWEEN 306 AND 340
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
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 306 AND 340')
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
    cat_dir = "Home Essentials"
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
    """, (product_id, prod_num, name, sku, desc, HOME_CAT_ID, stock))
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
    cat_dir    = "Home Essentials"
    local_cat  = os.path.join(IMAGE_BASE, cat_dir)
    remote_cat = f"{REMOTE_BASE}/{cat_dir}"

    os.makedirs(local_cat, exist_ok=True)

    # Ensure remote category directory exists (unencoded name with spaces)
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
        # CRITICAL: remote dir uses UNENCODED name (spaces) — Apache decodes %20 on serve
        remote_dir = f"{remote_cat}/{folder}"

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
        mkdir_remote(remote_cat, folder)   # spaces — not encoded
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


if __name__ == "__main__":
    main()
