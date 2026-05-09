"""
Add 35 best-selling Health & Wellness products:
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally  → image/Health & Wellness/{Folder Name}/image_N.jpg
  3. Uploads to agentorc.ca using UNENCODED folder names (spaces, not %20)
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)
  5. Generates sql/insert_35_health.sql from live DB data

Run from project root:
    python scripts/add_35_health.py
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
SQL_OUT      = r"D:\a\crm_agent\sql\insert_35_health.sql"
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

HW_CAT_ID = "fcaaec3d-21d4-461d-9dbe-849c7c14c7de"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 35 Best-selling Health & Wellness products ────────────────────────────────
# (product_number, sku, retail_cad, ws_pct, promo_ratio, stock,
#  full_product_name, folder_name, description, amazon_search_query)
PRODUCTS = [
    (271, 'HLT-VITA-C1000-001', 24.99, 0.18, 0.48, 420,
     "Jamieson Vitamin C 1000mg, 500 Tablets",
     "Jamieson Vitamin C 1000mg 500 Tablets",
     "Jamieson Vitamin C 1000 mg provides powerful antioxidant protection to support immune "
     "function and help reduce the duration of colds. Each tablet delivers 1000 mg of pure "
     "ascorbic acid for maximum potency. This value-size 500-tablet bottle is ideal for the "
     "whole family and made by Canada's most trusted vitamin brand. Non-GMO, gluten-free.",
     "Jamieson Vitamin C 1000mg 500 tablets"),

    (272, 'HLT-VITA-D3000-002', 19.99, 0.18, 0.48, 390,
     "Jamieson Vitamin D3 1000 IU, 400 Softgels",
     "Jamieson Vitamin D3 1000 IU 400 Softgels",
     "Jamieson Vitamin D3 1000 IU softgels support calcium absorption for strong bones and "
     "teeth, and help maintain a healthy immune system. Vitamin D3 is the preferred form for "
     "optimal absorption. Each softgel is easy to swallow and this 400-softgel value bottle "
     "provides over a year's supply. Made in Canada, non-GMO and gluten-free.",
     "Jamieson Vitamin D3 1000 IU softgels"),

    (273, 'HLT-OMEG-FISH-003', 29.99, 0.18, 0.48, 310,
     "Webber Naturals Omega-3 Fish Oil 1000mg, 300 Softgels",
     "Webber Naturals Omega-3 Fish Oil 1000mg 300 Softgels",
     "Webber Naturals Omega-3 Fish Oil provides 1000 mg of molecularly distilled, purified "
     "fish oil per softgel, delivering 300 mg of EPA and DHA to support heart health, brain "
     "function, and joint mobility. Each softgel is enteric-coated to reduce fishy aftertaste. "
     "Third-party tested for purity. 300-softgel value pack. Gluten-free and non-GMO.",
     "Webber Naturals omega-3 fish oil 1000mg 300 softgels"),

    (274, 'HLT-MAGA-GLYC-004', 22.99, 0.18, 0.50, 280,
     "Natural Calm Magnesium Citrate Powder, Raspberry-Lemon, 226 g",
     "Natural Calm Magnesium Citrate Powder 226g",
     "Natural Calm is the top-selling ionic magnesium supplement in Canada. This effervescent "
     "raspberry-lemon drink mix helps replenish magnesium depleted by stress, supports healthy "
     "sleep, reduces muscle cramps, and promotes relaxation. Made with magnesium citrate for "
     "superior absorption. Simply dissolve in hot or cold water. Vegan, non-GMO, and gluten-free.",
     "Natural Calm magnesium citrate powder raspberry lemon"),

    (275, 'HLT-ZINC-50MG-005', 12.99, 0.18, 0.50, 450,
     "Jamieson Zinc 50mg, 100 Tablets",
     "Jamieson Zinc 50mg 100 Tablets",
     "Jamieson Zinc 50 mg tablets provide an essential mineral that supports immune function, "
     "wound healing, and DNA synthesis. Zinc plays a key role in maintaining healthy skin and "
     "vision. Each tablet is easy to swallow and formulated for maximum absorption. This "
     "100-tablet bottle offers a convenient 3-month supply. Non-GMO, gluten-free, made in Canada.",
     "Jamieson Zinc 50mg tablets immune support"),

    (276, 'HLT-PROB-50BIL-006', 34.99, 0.18, 0.48, 260,
     "Renew Life Ultimate Flora Probiotic 50 Billion, 60 Capsules",
     "Renew Life Ultimate Flora Probiotic 50 Billion 60 Capsules",
     "Renew Life Ultimate Flora Probiotic delivers 50 billion live cultures from 12 diverse "
     "probiotic strains to support digestive balance, gut health, and immune function. The "
     "delayed-release capsules are designed to survive stomach acid and reach the intestines "
     "intact. Dairy-free, gluten-free, and no refrigeration required. 60-capsule supply.",
     "Renew Life Ultimate Flora probiotic 50 billion"),

    (277, 'HLT-COLL-POWD-007', 44.99, 0.18, 0.48, 230,
     "Vital Proteins Collagen Peptides Powder, Unflavored, 567 g",
     "Vital Proteins Collagen Peptides Powder Unflavored 567g",
     "Vital Proteins Collagen Peptides is a grass-fed, pasture-raised bovine collagen that "
     "supports healthy skin, hair, nails, bones, and joints. Each serving delivers 20 g of "
     "protein and 18 g of collagen peptides. Unflavored and easily dissolves in hot or cold "
     "liquids, smoothies, or coffee. Paleo and keto-friendly. No added sugars, dairy-free.",
     "Vital Proteins collagen peptides unflavored powder"),

    (278, 'HLT-PROT-WHEY-008', 59.99, 0.18, 0.48, 200,
     "Optimum Nutrition Gold Standard 100% Whey Protein, Double Rich Chocolate, 2 lb",
     "Optimum Nutrition Gold Standard Whey Protein 2lb Chocolate",
     "Optimum Nutrition Gold Standard 100% Whey is the world's best-selling whey protein "
     "supplement. Each serving provides 24 g of high-quality whey protein, including whey "
     "protein isolate as the primary ingredient, plus 5.5 g of BCAAs to support muscle "
     "recovery and growth. Only 1 g of sugar per serving. Banned substance tested.",
     "Optimum Nutrition Gold Standard whey protein double rich chocolate 2lb"),

    (279, 'HLT-PROT-PLAN-009', 54.99, 0.18, 0.48, 180,
     "Garden of Life Organic Plant-Based Protein Powder, Chocolate, 840 g",
     "Garden of Life Organic Plant Protein Powder Chocolate 840g",
     "Garden of Life Organic Plant-Based Protein provides 30 g of clean protein per serving "
     "from a blend of organic peas, sprouted grains, seeds, and legumes. Complete amino acid "
     "profile with added probiotics and enzymes for optimal digestion. USDA organic, non-GMO, "
     "vegan, gluten-free. Sweetened with stevia. NSF Certified for Sport.",
     "Garden of Life organic plant protein chocolate"),

    (280, 'HLT-CRTN-MONO-010', 27.99, 0.18, 0.48, 290,
     "Allmax Creatine Monohydrate Powder, 400 g",
     "Allmax Creatine Monohydrate Powder 400g",
     "Allmax 100% Pure Pharmaceutical Grade Creatine Monohydrate is micronized for "
     "fast dissolution and superior absorption. Creatine increases explosive strength, "
     "supports high-intensity training, and helps build lean muscle mass. Tested and "
     "verified for purity — no fillers, no additives, just 100% pure creatine. "
     "Unflavored and mixes easily with water or your favourite beverage. Keto-friendly.",
     "Allmax creatine monohydrate powder 400g"),

    (281, 'HLT-MEBT-BVIT-011', 21.99, 0.18, 0.48, 340,
     "Jamieson B12 Methylcobalamin 1000mcg, 60 Sublingual Tablets",
     "Jamieson B12 Methylcobalamin 1000mcg 60 Tablets",
     "Jamieson Methylcobalamin B12 1000 mcg provides the active, bioavailable form of "
     "Vitamin B12 for energy metabolism, nerve function, and red blood cell formation. "
     "Sublingual tablets dissolve under the tongue for rapid absorption — ideal for those "
     "with absorption challenges. Vegan-friendly, non-GMO, gluten-free. Made in Canada.",
     "Jamieson B12 methylcobalamin 1000mcg sublingual tablets"),

    (282, 'HLT-IRON-GENT-012', 16.99, 0.18, 0.50, 370,
     "Floradix Liquid Iron and Herbs, 500 ml",
     "Floradix Liquid Iron and Herbs 500ml",
     "Floradix Liquid Iron Formula is a gentle, easily absorbed iron supplement with "
     "organic fruit juices, vegetables, and herbs. Each 10 ml dose provides 7.5 mg of "
     "ferrous gluconate iron — gentle on the stomach with no constipation side effects. "
     "Enriched with B vitamins and Vitamin C to enhance iron absorption. "
     "Suitable for women, teens, vegetarians, and athletes. Free of preservatives and alcohol.",
     "Floradix liquid iron supplement 500ml"),

    (283, 'HLT-MEBT-FOAC-013', 13.99, 0.18, 0.50, 410,
     "Jamieson Folic Acid 1mg, 100 Tablets",
     "Jamieson Folic Acid 1mg 100 Tablets",
     "Jamieson Folic Acid 1 mg tablets provide an essential B vitamin that supports neural "
     "tube development, making it a critical supplement during pregnancy and for women of "
     "childbearing age. Folic acid also supports red blood cell formation and cardiovascular "
     "health. Each tablet is easy to swallow. 100-tablet supply. Non-GMO, gluten-free.",
     "Jamieson folic acid 1mg tablets"),

    (284, 'HLT-SLEP-MELT-014', 18.99, 0.18, 0.48, 320,
     "Jamieson Melatonin Extra Strength 10mg, 60 Tablets",
     "Jamieson Melatonin Extra Strength 10mg 60 Tablets",
     "Jamieson Melatonin Extra Strength 10 mg helps reset the sleep-wake cycle and "
     "promotes restful sleep without drowsiness the next day. Melatonin is a natural "
     "hormone produced by the body to regulate circadian rhythm — this supplement helps "
     "when sleep is disrupted by shift work, jet lag, or insomnia. Fast-dissolve tablets. "
     "Non-GMO, gluten-free. Made in Canada.",
     "Jamieson melatonin 10mg extra strength tablets"),

    (285, 'HLT-GLAB-CLEA-015', 15.99, 0.18, 0.48, 290,
     "Metamucil Daily Fibre Supplement, Orange Smooth, 48-Dose, 283 g",
     "Metamucil Daily Fibre Supplement Orange Smooth 283g",
     "Metamucil Daily Fibre Supplement with psyllium husk fibre helps promote digestive "
     "health, lower cholesterol, and maintain healthy blood sugar levels. The smooth orange "
     "flavour dissolves completely with no grittiness. 48-dose canister provides a convenient "
     "multi-week supply. Clinically proven to be effective in 2 weeks. Sugar-free option available.",
     "Metamucil fibre supplement orange smooth powder"),

    (286, 'HLT-ALOE-DRNK-016', 11.99, 0.18, 0.50, 350,
     "Lily of the Desert Aloe Vera Gel, Inner Fillet, 946 ml",
     "Lily of the Desert Aloe Vera Gel Inner Fillet 946ml",
     "Lily of the Desert Aloe Vera Gel is made from certified organic aloe vera and "
     "contains the inner fillet gel for maximum purity. It supports digestive health, "
     "soothes the stomach lining, and promotes natural detoxification. Free of artificial "
     "colours, flavours, and preservatives. Certified organic, kosher, and vegan. "
     "Can be consumed directly or mixed into juice or smoothies.",
     "Lily of the Desert aloe vera juice inner fillet"),

    (287, 'HLT-PROT-BAR3-017', 39.99, 0.18, 0.48, 240,
     "Quest Nutrition Protein Bar, Chocolate Chip Cookie Dough, 12 Count",
     "Quest Nutrition Protein Bar Chocolate Chip Cookie Dough 12 Count",
     "Quest Protein Bars deliver 21 g of protein with only 4-5 g of net carbs per bar, "
     "making them ideal for keto, low-carb, and high-protein diets. The Chocolate Chip "
     "Cookie Dough flavour features real chocolate chips and a doughy texture that "
     "satisfies cravings guilt-free. Gluten-free, soy-free. 150 calories per bar. "
     "No added sugar — sweetened with erythritol and stevia.",
     "Quest protein bars chocolate chip cookie dough 12 pack"),

    (288, 'HLT-BCHA-PWDR-018', 47.99, 0.18, 0.48, 210,
     "BioSteel BCAA Powder, Watermelon, 315 g",
     "BioSteel BCAA Powder Watermelon 315g",
     "BioSteel BCAA Powder provides a 2:1:1 ratio of branched-chain amino acids (leucine, "
     "isoleucine, valine) to support muscle recovery, reduce exercise-induced muscle "
     "soreness, and preserve lean muscle. Made with clean, natural ingredients — no "
     "artificial colours, flavours, or sweeteners. Refreshing watermelon flavour. "
     "NSF Certified for Sport. Vegan and gluten-free.",
     "BioSteel BCAA powder watermelon"),

    (289, 'HLT-ELCT-HYDR-019', 22.99, 0.18, 0.48, 310,
     "Nuun Sport Electrolyte Tablets, Variety Pack, 40 Tablets",
     "Nuun Sport Electrolyte Tablets Variety Pack 40 Tablets",
     "Nuun Sport Electrolyte Tablets provide a clean, fast-dissolving electrolyte solution "
     "to replenish sodium, potassium, magnesium, and calcium lost through sweat. Each tube "
     "contains 10 tablets — this variety 4-pack includes 4 flavours. Only 15 calories per "
     "tablet. Non-GMO, gluten-free, dairy-free, and certified vegan. Perfect for running, "
     "cycling, hiking, and workouts.",
     "Nuun Sport electrolyte tablets variety pack"),

    (290, 'HLT-PRER-WRKT-020', 49.99, 0.18, 0.48, 190,
     "C4 Original Pre-Workout Powder, Fruit Punch, 195 g (30 Servings)",
     "C4 Original Pre-Workout Powder Fruit Punch 195g 30 Servings",
     "C4 Original Pre-Workout is America's #1 best-selling pre-workout with over 2 billion "
     "servings sold. Each scoop delivers 150 mg of caffeine, CarnoSyn Beta-Alanine, "
     "creatine nitrate, and arginine AKG to boost energy, endurance, pumps, and focus. "
     "Fruit punch flavour, 30 servings per container. Banned substance tested, NSF certified.",
     "C4 Original pre-workout powder fruit punch 30 servings"),

    (291, 'HLT-TURC-CURC-021', 26.99, 0.18, 0.48, 280,
     "Webber Naturals Turmeric with Black Pepper 500mg, 180 Capsules",
     "Webber Naturals Turmeric Black Pepper 500mg 180 Capsules",
     "Webber Naturals Turmeric with Black Pepper extract provides 500 mg of curcumin-rich "
     "turmeric root per capsule, enhanced with BioPerine black pepper extract to improve "
     "bioavailability by up to 2000%. Supports joint health, reduces inflammation, and "
     "provides antioxidant protection. 180-capsule value bottle. Non-GMO, gluten-free, "
     "dairy-free. Made in Canada.",
     "Webber Naturals turmeric curcumin black pepper 500mg 180 capsules"),

    (292, 'HLT-ASWA-ADPT-022', 32.99, 0.18, 0.48, 240,
     "Natural Factors Ashwagandha KSM-66, 300mg, 60 Capsules",
     "Natural Factors Ashwagandha KSM-66 300mg 60 Capsules",
     "Natural Factors Ashwagandha KSM-66 features the most clinically studied full-spectrum "
     "ashwagandha root extract on the market. 300 mg per capsule supports stress reduction, "
     "cortisol balance, mental clarity, and physical endurance. KSM-66 is the highest "
     "concentration, full-spectrum root extract available. Vegan, non-GMO, gluten-free.",
     "Natural Factors ashwagandha KSM-66 300mg"),

    (293, 'HLT-GREL-CAPS-023', 17.99, 0.18, 0.50, 330,
     "Webber Naturals Garlic 500mg, 180 Enteric-Coated Softgels",
     "Webber Naturals Garlic 500mg 180 Enteric-Coated Softgels",
     "Webber Naturals Garlic provides 500 mg of concentrated garlic per enteric-coated "
     "softgel for cardiovascular support, immune function, and antioxidant protection. "
     "The enteric coating prevents garlic breath and stomach discomfort. Each softgel "
     "is equivalent to one fresh garlic clove. 180-softgel value bottle. "
     "Non-GMO, gluten-free, made in Canada.",
     "Webber Naturals garlic 500mg enteric coated softgels"),

    (294, 'HLT-COQT-100MG-024', 38.99, 0.18, 0.48, 210,
     "Jamieson CoQ10 100mg, 90 Softgels",
     "Jamieson CoQ10 100mg 90 Softgels",
     "Jamieson CoQ10 100 mg provides coenzyme Q10 in a lipid-based softgel for superior "
     "absorption. CoQ10 supports cellular energy production in the mitochondria and is a "
     "powerful antioxidant that protects the heart and other vital organs. Especially "
     "important for those taking statin medications. 90-softgel supply. Non-GMO, gluten-free.",
     "Jamieson CoQ10 100mg softgels heart health"),

    (295, 'HLT-EYEL-LUTEIN-025', 28.99, 0.18, 0.48, 250,
     "Webber Naturals Lutein 20mg with Zeaxanthin, 60 Softgels",
     "Webber Naturals Lutein 20mg Zeaxanthin 60 Softgels",
     "Webber Naturals Lutein 20 mg with Zeaxanthin supports macular health and protects "
     "against blue light and UV-induced oxidative damage to the eyes. Lutein and zeaxanthin "
     "are the only carotenoids found in the retina and are essential for long-term vision "
     "health. Each softgel delivers clinically relevant doses. Non-GMO, gluten-free.",
     "Webber Naturals lutein zeaxanthin eye health softgels"),

    (296, 'HLT-GCSM-JINT-026', 35.99, 0.18, 0.48, 220,
     "Schiff Glucosamine Plus MSM, 1500mg, 150 Coated Tablets",
     "Schiff Glucosamine Plus MSM 1500mg 150 Tablets",
     "Schiff Glucosamine Plus MSM provides 1500 mg of glucosamine sulfate and 1500 mg of "
     "MSM (methylsulfonylmethane) per serving to support joint cartilage, flexibility, and "
     "mobility. A trusted joint health formula recommended by orthopedic specialists. "
     "Coated tablets for easy swallowing. 150-tablet supply — 75 days when taken as directed. "
     "Gluten-free, no artificial colours or flavours.",
     "Schiff glucosamine MSM 1500mg joint health tablets"),

    (297, 'HLT-HYAL-ACID-027', 31.99, 0.18, 0.48, 240,
     "NOW Supplements Hyaluronic Acid 100mg, 120 Veg Capsules",
     "NOW Supplements Hyaluronic Acid 100mg 120 Veg Capsules",
     "NOW Hyaluronic Acid 100 mg with L-Proline, Alpha Lipoic Acid, and Grape Seed Extract "
     "supports healthy skin hydration, joint lubrication, and connective tissue health. "
     "Hyaluronic acid is a key component of synovial fluid and skin matrix. "
     "Vegetarian capsules. GMP quality assured, non-GMO. 120-capsule supply.",
     "NOW Supplements hyaluronic acid 100mg 120 capsules"),

    (298, 'HLT-MLTT-WOMN-028', 24.99, 0.18, 0.48, 310,
     "Centrum Women Multivitamin, 200 Tablets",
     "Centrum Women Multivitamin 200 Tablets",
     "Centrum Women Multivitamin is specially formulated with key nutrients to support "
     "women's health, including iron, folic acid, calcium, and B vitamins for energy "
     "metabolism. Each tablet provides 22 essential vitamins and minerals. Free from "
     "artificial flavours and sweeteners. 200-tablet value bottle — over 6 months' supply. "
     "Gluten-free, non-GMO verified.",
     "Centrum Women multivitamin 200 tablets"),

    (299, 'HLT-MLTT-MENS-029', 24.99, 0.18, 0.48, 300,
     "Centrum Men Multivitamin, 200 Tablets",
     "Centrum Men Multivitamin 200 Tablets",
     "Centrum Men Multivitamin is formulated to support men's health with key nutrients "
     "including lycopene, B vitamins for energy, zinc for immune support, and selenium "
     "for antioxidant protection. Each tablet provides 24 essential vitamins and minerals. "
     "200-tablet value bottle — over 6 months' supply. Gluten-free, non-GMO verified. "
     "No artificial flavours or sweeteners.",
     "Centrum Men multivitamin 200 tablets"),

    (300, 'HLT-CHLD-GUMI-030', 17.99, 0.18, 0.48, 360,
     "Jamieson Gummy Vitamins for Kids, 60 Gummies",
     "Jamieson Gummy Vitamins for Kids 60 Gummies",
     "Jamieson Gummy Vitamins for Kids provide a complete blend of essential vitamins and "
     "minerals in a delicious, easy-to-take gummy format that kids love. Each gummy delivers "
     "vitamins A, C, D, E, B6, B12, biotin, and pantothenic acid to support growth, immunity, "
     "and energy. No artificial colours or flavours, made with natural fruit flavours. "
     "Gluten-free and non-GMO. Made in Canada.",
     "Jamieson gummy vitamins for kids multivitamin"),

    (301, 'HLT-PREG-VITA-031', 29.99, 0.18, 0.48, 270,
     "Jamieson Prenatal Vitamin with DHA, 100 Softgels",
     "Jamieson Prenatal Vitamin with DHA 100 Softgels",
     "Jamieson Prenatal Vitamin with DHA provides comprehensive nutritional support for "
     "mother and baby during pregnancy and breastfeeding. Each softgel delivers folic acid "
     "for neural tube development, iron for healthy blood, plus DHA omega-3 for fetal brain "
     "and eye development. Gentle on the stomach with no fishy aftertaste. "
     "100-softgel supply. Non-GMO, made in Canada.",
     "Jamieson prenatal vitamin DHA softgels"),

    (302, 'HLT-SLEN-CLEN-032', 42.99, 0.18, 0.48, 200,
     "Progressive Harmonized Protein Shake, Natural Vanilla Hazelnut, 840g",
     "Progressive Harmonized Protein Shake Vanilla Hazelnut 840g",
     "Progressive Harmonized Protein provides 20 g of protein per serving from a balanced "
     "blend of whey, egg white, and milk protein isolates for sustained amino acid release. "
     "Enhanced with digestive enzymes, probiotics, and superfoods. No artificial sweeteners, "
     "colours, or flavours. Natural vanilla hazelnut flavour. 840 g canister. "
     "Gluten-free, non-GMO. Made in Canada.",
     "Progressive Harmonized protein shake vanilla hazelnut"),

    (303, 'HLT-GREL-SPRUT-033', 23.99, 0.18, 0.48, 260,
     "Garden of Life Dr. Formulated Probiotics Once Daily Women's, 30 Capsules",
     "Garden of Life Dr Formulated Probiotics Once Daily Womens 30 Capsules",
     "Garden of Life Dr. Formulated Probiotics Once Daily Women's provides 50 billion CFU "
     "from 16 probiotic strains specially selected for women's health, including Lactobacillus "
     "strains to support vaginal health and immune function. Shelf-stable — no refrigeration "
     "required. Made with organic prebiotic fiber. Certified gluten-free and non-GMO. "
     "Once-daily convenience.",
     "Garden of Life Dr Formulated probiotic women once daily 30 capsules"),

    (304, 'HLT-SPIR-ALGE-034', 27.99, 0.18, 0.48, 230,
     "NOW Foods Spirulina 500mg, 500 Tablets",
     "NOW Foods Spirulina 500mg 500 Tablets",
     "NOW Foods Spirulina provides a concentrated source of whole-food nutrition from "
     "blue-green algae. Spirulina is rich in complete protein (60%), B vitamins, iron, "
     "essential fatty acids, and powerful antioxidants including phycocyanin. Supports "
     "immune health, energy, and detoxification. Each tablet is 500 mg. 500-tablet value "
     "bottle. Non-GMO, GMP certified, vegan and gluten-free.",
     "NOW Foods spirulina 500mg tablets"),

    (305, 'HLT-BERT-PRFL-035', 36.99, 0.18, 0.48, 210,
     "Vega One All-in-One Nutritional Shake, French Vanilla, 876g",
     "Vega One All-in-One Nutritional Shake French Vanilla 876g",
     "Vega One All-in-One Nutritional Shake delivers 20 g of plant-based protein, 50% of "
     "daily vitamins and minerals, 6 g of fibre, 1.5 g of Omega-3 ALA, probiotics, and "
     "greens — all in one satisfying scoop. Made with pea protein, flaxseed, and organic "
     "greens. No artificial sweeteners, colours, or flavours. French vanilla flavour. "
     "Certified vegan, gluten-free, non-GMO. Made in Canada.",
     "Vega One all-in-one nutritional shake French vanilla 876g"),
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

def generate_sql(num_products, num_pricing, num_images):
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
    w('-- INSERT 35 best-selling Health & Wellness products + pricing + images')
    w(f'-- Generated: {NOW[:10]}')
    w('-- Products  : 35 rows  (product_number 271-305)')
    w('-- Pricing   : 105 rows (Retail + Promo + Wholesale per product)')
    w('-- Images    : 175 rows (5 images per product)')
    w('-- Category  : Health & Wellness  (fcaaec3d-21d4-461d-9dbe-849c7c14c7de)')
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
        WHERE c.category_name = 'Health & Wellness' AND p.product_number >= 271
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
        WHERE p.product_number BETWEEN 271 AND 305
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
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 271 AND 305')
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
        WHERE p.product_number BETWEEN 271 AND 305
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
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 271 AND 305')
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
    cat_dir = "Health & Wellness"
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
    """, (product_id, prod_num, name, sku, desc, HW_CAT_ID, stock))
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
    for i, img_url in enumerate(img_urls, 1):
        img_file = f"image_{i}.jpg"
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
    cat_dir     = "Health & Wellness"
    local_cat   = os.path.join(IMAGE_BASE, cat_dir)
    remote_cat  = f"{REMOTE_BASE}/{cat_dir}"

    os.makedirs(local_cat, exist_ok=True)

    # Ensure remote category directory exists
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
        candidates = []
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
        img_urls_for_db = [os.path.basename(p) for p in downloaded]
        try:
            product_id, ws, promo = db_insert(
                conn, prod_num, sku, name, desc,
                retail, ws_pct, promo_ratio, stock,
                img_urls_for_db, folder_enc
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
    generate_sql(succeeded, total_pricing, total_imgs)

    print(f"\n{'='*70}")
    print(f"DONE.  Succeeded: {succeeded}/{len(PRODUCTS)}")


if __name__ == "__main__":
    main()
