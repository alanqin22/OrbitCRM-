"""
Add 31 best-selling Office Supplies products:
  1. Downloads 5 images per product (Amazon.ca scraping)
  2. Saves locally  → image/Office Supplies/{Folder Name}/image_N.jpg
  3. Uploads to agentorc.ca using UNENCODED folder names (spaces, not %20)
  4. Inserts into Railway PostgreSQL (products, product_image, product_pricing)
  5. Generates sql/insert_31_office_supplies.sql from live DB data

Run from project root:
    python scripts/add_31_office_supplies.py
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
SQL_OUT      = r"D:\a\crm_agent\sql\insert_31_office_supplies.sql"
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

OFFICE_CAT_ID = "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

# ── 31 Best-selling Office Supplies products ──────────────────────────────────
# (product_number, sku, retail_cad, ws_pct, promo_ratio, stock,
#  full_product_name, folder_name, description, amazon_search_query)
PRODUCTS = [
    (341, 'OFF-HP-PAPR-001', 12.99, 0.18, 0.50, 1200,
     "HP Printer Paper 8.5x11, Ream of 500 Sheets",
     "HP Printer Paper 8.5x11 Ream 500 Sheets",
     "HP Printer Paper delivers reliable, jam-free printing for everyday office and home use. "
     "The 8.5 x 11-inch, 20 lb / 75 gsm paper works with all inkjet and laser printers, "
     "copiers, and fax machines. Acid-free for longer-lasting documents. Bright white "
     "ColorLok technology ensures vivid colours, darker blacks, and faster drying for "
     "professional-quality results. 500 sheets per ream.",
     "HP printer paper 8.5x11 ream 500 sheets"),

    (342, 'OFF-POST-NOTE-002', 14.99, 0.18, 0.50, 850,
     "Post-it Notes, 3x3 in, Canary Yellow, 12-Pack (100 Sheets/Pad)",
     "Post-it Notes 3x3 Canary Yellow 12-Pack",
     "Post-it Notes are the original self-stick removable notes. The iconic canary yellow "
     "colour is the most recognized note colour in the world. Each pad contains 100 sheets "
     "that stick and restick without leaving residue. Perfect for reminders, messages, "
     "and desk organisation. 12-pack provides great value for office and home. "
     "Works on most surfaces including glass, painted walls, and paper.",
     "Post-it Notes 3x3 canary yellow 12 pack 100 sheets"),

    (343, 'OFF-SHRP-MARK-003', 18.99, 0.18, 0.50, 680,
     "Sharpie Permanent Markers, Fine Point, Assorted Colors, 24-Pack",
     "Sharpie Permanent Markers Fine Point Assorted 24-Pack",
     "Sharpie Permanent Markers deliver bold, precise lines on almost any surface — paper, "
     "plastic, metal, glass, and more. The fine point tip is ideal for writing, labelling, "
     "and drawing. Fade-resistant and water-resistant ink stands up to daily use. "
     "Quick-drying formula reduces smearing. This 24-pack includes a variety of colours "
     "for colour-coding files, projects, and presentations.",
     "Sharpie permanent markers fine point assorted colors 24 pack"),

    (344, 'OFF-BIC-BPEN-004', 9.99, 0.18, 0.50, 1100,
     "BIC Cristal Xtra Smooth Ball Pen, Medium 1.0mm, Black, 20-Pack",
     "BIC Cristal Xtra Smooth Ballpoint Pen Black 20-Pack",
     "BIC Cristal Xtra Smooth Ballpoint Pens are the world's best-selling pen, renowned "
     "for their smooth, consistent writing performance. The 1.0mm medium tip produces a "
     "clean, clear line every time. The transparent barrel lets you see the ink level. "
     "Tungsten carbide ball for smooth ink flow. Non-smear, non-smudge ink. "
     "20-pack value set for home and office use.",
     "BIC Cristal Xtra Smooth ballpoint pen black medium 20 pack"),

    (345, 'OFF-PILOT-GPEN-005', 19.99, 0.18, 0.48, 720,
     "PILOT G2 Premium Gel Ink Rollerball Pens, Fine Point 0.7mm, Black, 12-Pack",
     "PILOT G2 Gel Ink Rollerball Pen Black Fine Point 12-Pack",
     "PILOT G2 Pens deliver a smooth, comfortable writing experience with premium gel ink "
     "that glides effortlessly across paper. The retractable design with rubberized grip "
     "provides all-day writing comfort. Refillable cartridge for long-lasting value. "
     "The 0.7mm fine point produces crisp, precise lines. Consistent ink flow prevents "
     "skipping and blotching. America's #1 selling gel ink pen brand. 12-pack.",
     "Pilot G2 premium gel ink pen black fine point 12 pack"),

    (346, 'OFF-SCOT-TAPE-006', 12.99, 0.18, 0.50, 930,
     "Scotch Magic Tape, 3/4 in x 1000 in, 6-Pack",
     "Scotch Magic Tape 3-4 in x 1000 in 6-Pack",
     "Scotch Magic Tape is virtually invisible on paper, making it ideal for wrapping gifts, "
     "repairing torn documents, and everyday office tasks. The matte finish makes it "
     "writable with pen, pencil, or marker. Repositionable without tearing. "
     "Leaves no residue when removed cleanly from most surfaces. "
     "This 6-pack provides long-lasting value. Each roll is 3/4 in x 1000 in.",
     "Scotch Magic Tape 3/4 inch 6 pack office"),

    (347, 'OFF-SWIN-STPLR-007', 24.99, 0.18, 0.48, 460,
     "Swingline Stapler, Heavy Duty, Desktop, 25 Sheet Capacity, 1000 Staples Included",
     "Swingline Heavy Duty Desktop Stapler 25 Sheet 1000 Staples",
     "Swingline Heavy Duty Desktop Stapler handles up to 25 sheets at once with ease. "
     "The jam-resistant design prevents frustrating misfeeds. Top-loading mechanism "
     "makes refilling quick and simple. Low-force stapling reduces hand fatigue for "
     "high-volume use. Includes 1000 standard 26/6 staples to get started. "
     "Durable metal construction for long-lasting performance. Works with standard and "
     "cartridge staples.",
     "Swingline heavy duty desktop stapler 25 sheet capacity"),

    (348, 'OFF-AVRY-LABL-008', 21.99, 0.18, 0.48, 540,
     "Avery Easy Peel White Mailing Labels for Laser Printers, 1 x 2-5/8 in, 750 Labels",
     "Avery Easy Peel White Labels Laser 1x2-5-8 in 750 Labels",
     "Avery Easy Peel White Labels feature a special EasyPeel strip that reveals the label "
     "edge for clean, easy removal from the sheet. Permanent adhesive bonds securely to "
     "envelopes, packages, and files. Works with all laser printers for crisp, professional "
     "results. 30 labels per sheet on standard 8.5x11 paper. Use Avery Design & Print "
     "templates for easy customization. 750 labels total.",
     "Avery Easy Peel white labels laser printer 1x2 5/8 750 labels"),

    (349, 'OFF-MEAD-NTBK-009', 18.99, 0.18, 0.50, 620,
     "Mead Spiral Notebooks, 1-Subject, College Ruled, 70 Sheets, 5-Pack",
     "Mead Spiral Notebooks College Ruled 70 Sheets 5-Pack",
     "Mead Spiral Notebooks feature durable covers that protect pages from everyday wear "
     "and tear. College-ruled lines provide adequate space for neat, organized notes. "
     "Perforated pages tear out cleanly without ragged edges. The spiral binding lies flat "
     "when open and allows the notebook to fold completely back. "
     "70 sheets (140 pages) per notebook. This 5-pack provides excellent value for "
     "students and professionals.",
     "Mead spiral notebook college ruled 70 sheets 5 pack"),

    (350, 'OFF-EXPO-DRYM-010', 16.99, 0.18, 0.48, 580,
     "EXPO Low-Odor Dry Erase Markers, Chisel Tip, Assorted Colors, 8-Pack",
     "EXPO Low-Odor Dry Erase Markers Chisel Tip Assorted 8-Pack",
     "EXPO Low-Odor Dry Erase Markers deliver vibrant, bold colour on whiteboards with "
     "a low-odor formula that's better for enclosed spaces. The chisel tip creates both "
     "broad and fine lines for versatile marking. Easy-to-erase — wipe clean with a "
     "dry eraser or cloth. Ink resists drying out if cap is left off for up to 7 days. "
     "This 8-pack includes black, blue, red, green, purple, orange, brown, and yellow.",
     "EXPO low odor dry erase markers chisel tip assorted 8 pack"),

    (351, 'OFF-PNDX-HFLD-011', 19.99, 0.18, 0.48, 490,
     "Pendaflex Hanging File Folders, Letter Size, Assorted Colors, 25-Pack",
     "Pendaflex Hanging File Folders Letter Assorted Colors 25-Pack",
     "Pendaflex Hanging File Folders keep your desk and drawers organised with colour-coded "
     "filing. The reinforced top rail and frame rods are pre-assembled for easy setup. "
     "Scored for 2-inch expansion. Includes clear plastic tabs and white inserts for "
     "custom labelling. Made from recycled materials. Works with standard file cabinet "
     "drawers. Letter size (8.5 x 11 in). 25-pack in assorted colours.",
     "Pendaflex hanging file folders letter assorted colors 25 pack"),

    (352, 'OFF-3MCM-STPS-012', 22.99, 0.18, 0.48, 410,
     "Command Large Picture Hanging Strips, 14 Pairs",
     "Command Large Picture Hanging Strips 14 Pairs",
     "Command Large Picture Hanging Strips let you hang pictures and frames without nails, "
     "holes, or marks on your walls. The strong adhesive holds securely and removes cleanly "
     "without damaging paint or surfaces. Holds up to 3.6 kg (8 lb) per pair. "
     "Each pair uses two interlocking strips for a firm connection. Ideal for frames, "
     "canvases, and large photos. Works on smooth, finished walls, glass, tile, and metal. "
     "14 pairs included.",
     "Command large picture hanging strips adhesive 14 pairs"),

    (353, 'OFF-ACCO-BNDR-013', 29.99, 0.18, 0.48, 380,
     "ACCO 1-Inch 3-Ring View Binder with D-Ring, White, 6-Pack",
     "ACCO 3-Ring View Binder 1-Inch D-Ring White 6-Pack",
     "ACCO View Binders feature a clear overlay on front, back, and spine to customize with "
     "inserts for professional presentation. The heavy-duty D-ring holds more pages and "
     "prevents rings from snagging. 1-inch capacity holds approximately 200 sheets. "
     "Durable polypropylene cover resists stains, tears, and spills. "
     "Acid-free for document preservation. This 6-pack provides great value "
     "for office and school use.",
     "ACCO 3 ring view binder 1 inch D ring white 6 pack"),

    (354, 'OFF-ARTZ-CLPN-014', 24.99, 0.18, 0.48, 350,
     "Arteza Colored Pencils, Set of 48 Assorted Colors, Pre-Sharpened",
     "Arteza Colored Pencils Set of 48 Assorted Pre-Sharpened",
     "Arteza Colored Pencils feature a soft, pigment-rich core that blends and layers "
     "smoothly for vibrant results. The pre-sharpened tips are ready to use right out "
     "of the box. Break-resistant leads with superior colour saturation. "
     "Ideal for adult colouring books, sketching, illustration, and classroom use. "
     "Triangular barrel prevents rolling. Each set includes 48 unique colours "
     "ranging from soft pastels to vivid brights.",
     "Arteza colored pencils 48 assorted colors pre-sharpened set"),

    (355, 'OFF-BROT-LBMK-015', 39.99, 0.16, 0.46, 290,
     "Brother P-Touch PTD210 Label Maker with 1 Tape Cassette",
     "Brother P-Touch PTD210 Label Maker with Tape Cassette",
     "Brother P-Touch PTD210 Label Maker creates professional-quality labels for the home "
     "and office. Choose from 14 font sizes, 10 font styles, and multiple frames and "
     "symbols. One-touch auto format keys make labelling quick and easy. The 2-line display "
     "shows your text as you type. Battery-powered for cord-free use. Compatible with all "
     "TZ and TZe tape cassettes 3.5mm to 18mm wide. Includes one black-on-white TZ tape.",
     "Brother P-Touch PTD210 label maker with tape cassette"),

    (356, 'OFF-QRTT-WBRD-016', 49.99, 0.16, 0.46, 240,
     "Quartet Magnetic Dry-Erase Whiteboard, Melamine, 17 x 23 Inch",
     "Quartet Magnetic Dry-Erase Whiteboard Melamine 17x23 Inch",
     "Quartet Magnetic Whiteboard features a melamine surface that is compatible with dry "
     "erase markers and magnets for versatile use. Sturdy aluminum frame provides a "
     "professional look while protecting the edges. Wall-mounting hardware included. "
     "17 x 23 inch size is ideal for home offices, dorm rooms, and small business spaces. "
     "Ghost-resistant surface ensures clean erasing. Use magnets to hold notes and documents.",
     "Quartet magnetic dry erase whiteboard melamine 17x23 inch"),

    (357, 'OFF-XACT-PNSH-017', 19.99, 0.18, 0.50, 420,
     "X-ACTO Classic Manual Pencil Sharpener with Receptacle",
     "X-ACTO Classic Manual Pencil Sharpener with Receptacle",
     "X-ACTO Classic Manual Pencil Sharpener delivers the reliable, sharp points "
     "professionals demand. The self-cleaning mechanism keeps the blade sharp longer. "
     "Built-in shavings receptacle catches debris for mess-free sharpening. "
     "Suction cup base keeps the sharpener firmly in place. "
     "Accommodates standard and jumbo pencils. Durable all-metal construction "
     "built to last through years of daily use. Table-mount compatible.",
     "X-ACTO classic manual pencil sharpener with receptacle"),

    (358, 'OFF-SMAD-FLDR-018', 29.99, 0.18, 0.48, 330,
     "Smead Manila File Folders, Letter Size, 1/3 Cut, 100-Pack",
     "Smead Manila File Folders Letter 1/3 Cut 100-Pack",
     "Smead Manila File Folders are made from sturdy, heavyweight stock for durable "
     "document storage. The 1/3 cut tabs are positioned at the left, center, and right "
     "for easy labelling and visibility in file drawers. Scored for 3/4-inch expansion. "
     "Letter size (8.5 x 11 in) works with standard file cabinets. "
     "Acid-free for long-term document preservation. "
     "100-pack provides exceptional value for busy offices.",
     "Smead manila file folders letter 1/3 cut 100 pack"),

    (359, 'OFF-WSTC-RULR-019', 9.99, 0.18, 0.50, 700,
     "Westcott 12-Inch Stainless Steel Ruler with Non-Slip Cork Base",
     "Westcott 12-Inch Stainless Steel Ruler Non-Slip Cork Base",
     "Westcott 12-Inch Stainless Steel Ruler features clear, accurate measurements in "
     "both inches (1/16 increments) and centimetres (1mm increments). The non-slip cork "
     "backing prevents sliding for precise measurement and straight-edge cutting. "
     "Durable stainless steel construction resists bending and warping. "
     "Beveled edge design reduces ink smearing when used with drafting pens. "
     "Suitable for use with rotary cutters and craft knives.",
     "Westcott 12 inch stainless steel ruler non-slip cork base"),

    (360, 'OFF-AVRY-DIVD-020', 19.99, 0.18, 0.48, 480,
     "Avery 5-Tab Dividers for 3-Ring Binders, Insertable, 24 Sets",
     "Avery 5-Tab Binder Dividers Insertable 24 Sets",
     "Avery Insertable Dividers make it easy to organize binders and reference materials. "
     "The clear tabs allow for customizable labels — simply insert your own labels "
     "for a professional, personalized look. Reinforced holes prevent tearing. "
     "Works with Avery and other standard label formats. Prepunched for use in "
     "3-ring binders. 5 tabs per set, 24 sets total (120 dividers). "
     "Acid-free and archival-safe.",
     "Avery 5 tab binder dividers insertable 24 sets"),

    (361, 'OFF-LRLL-TRAY-021', 24.99, 0.18, 0.48, 360,
     "Lorell Mesh Desktop Document Tray, Letter Size, Black",
     "Lorell Mesh Desktop Document Tray Letter Size Black",
     "Lorell Mesh Desktop Document Tray keeps your workspace tidy by corralling loose "
     "papers, files, and mail in one place. The open-mesh design lets you quickly "
     "identify contents without lifting papers. Stackable design allows multiple "
     "trays to be added vertically as your needs grow. "
     "Non-slip rubber feet protect your desk surface. "
     "Letter size holds 8.5 x 11 in documents. Durable black steel mesh construction.",
     "Lorell mesh desktop document tray letter size black"),

    (362, 'OFF-ROLD-BCRD-022', 34.99, 0.17, 0.47, 210,
     "Rolodex Wood Tones Desktop Business Card File, Holds 250 Cards",
     "Rolodex Wood Tones Desktop Business Card File 250 Cards",
     "Rolodex Wood Tones Business Card File brings a classic, professional look to your "
     "desktop. The rotating design provides quick access to all 250 business cards. "
     "Alphabetical index tabs help you find contacts in seconds. "
     "Includes 250 sleeves and A-Z index cards. The rich wood-tone finish complements "
     "traditional and modern office decor. Durable construction for lasting "
     "organisation. Ideal for reception desks and executive offices.",
     "Rolodex wood tones desktop business card file 250 cards"),

    (363, 'OFF-CAMB-MNTBK-023', 16.99, 0.18, 0.50, 440,
     "Cambridge Business Notebook, 1-Subject, Meeting Planner, 8.5 x 11, 80 Sheets",
     "Cambridge Business Notebook Meeting Planner 8.5x11 80 Sheets",
     "Cambridge Meeting Planner Notebook helps you stay organised during meetings with "
     "a structured format that prompts you to capture key information: attendees, "
     "objectives, action items, and follow-ups. The twin-wire binding opens flat "
     "for comfortable writing. Micro-perforated pages tear out cleanly. "
     "Heavyweight covers protect against daily wear. 80 ruled sheets "
     "(160 pages). Letter size, 8.5 x 11 in.",
     "Cambridge business notebook meeting planner 8.5x11 80 sheets"),

    (364, 'OFF-HP67X-CART-024', 39.99, 0.15, 0.45, 310,
     "HP 67XL Black High Yield Original Ink Cartridge",
     "HP 67XL Black High Yield Original Ink Cartridge",
     "HP 67XL Black High Yield Ink Cartridge delivers up to 480 pages per cartridge — "
     "3x more pages than the standard cartridge. Original HP ink provides reliable, "
     "high-quality printing for documents and everyday tasks. Designed for HP DeskJet, "
     "ENVY, and ENVY Inspire printers. Smart chip ensures precise ink tracking and "
     "low-ink alerts. Fade-resistant ink keeps documents looking great for decades. "
     "Easy drop-in installation.",
     "HP 67XL black high yield original ink cartridge"),

    (365, 'OFF-CANN-PRNT-025', 89.99, 0.15, 0.45, 180,
     "Canon PIXMA MG3620 Wireless All-In-One Color Inkjet Printer",
     "Canon PIXMA MG3620 Wireless All-In-One Color Inkjet Printer",
     "Canon PIXMA MG3620 Wireless All-In-One Inkjet Printer lets you print, copy, "
     "and scan wirelessly from anywhere in your home or office. Auto Duplex Printing "
     "automatically prints on both sides of the page, saving paper and money. "
     "Print from your smartphone or tablet using the Canon PRINT app or Apple AirPrint. "
     "Maximum print resolution: 4800 x 1200 dpi for sharp, vivid results. "
     "Quiet mode for undisturbed printing. Compatible with iOS and Android.",
     "Canon PIXMA MG3620 wireless all-in-one color inkjet printer"),

    (366, 'OFF-AVRY-BTAB-026', 14.99, 0.18, 0.50, 590,
     "Avery Big Tab Insertable Dividers, 8-Tab, 3 Sets",
     "Avery Big Tab Insertable Dividers 8-Tab 3 Sets",
     "Avery Big Tab Insertable Dividers feature extra-wide tabs that are 50% bigger than "
     "standard tabs for maximum visibility in binders. The clear tabs allow you to "
     "insert custom labels for a personalized, professional look. "
     "Reinforced holes prevent tearing with heavy use. "
     "Works with most laser and inkjet printers for easy label printing. "
     "8 tabs per set, 3 sets total (24 dividers). Letter size, compatible with "
     "all standard 3-ring binders.",
     "Avery Big Tab insertable dividers 8 tab 3 sets"),

    (367, 'OFF-POST-FLAG-027', 12.99, 0.18, 0.50, 750,
     "Post-it Flags, Assorted Bright Colors, 140 Flags/Pack",
     "Post-it Flags Assorted Bright Colors 140 Flags",
     "Post-it Flags stick and restick without tearing pages, making them perfect for "
     "bookmarking, flagging, and highlighting important information in documents and books. "
     "The bright assorted colours are ideal for colour-coding chapters, sections, or "
     "priority levels. Tabs extend beyond the page for easy retrieval. "
     "Repositionable without leaving residue. 140 flags per pack in "
     "assorted bright colours including pink, orange, yellow, green, and blue.",
     "Post-it flags assorted bright colors 140 count pack"),

    (368, 'OFF-STDR-ERSR-028', 8.99, 0.18, 0.50, 920,
     "Staedtler Mars Plastic Erasers, 5-Pack",
     "Staedtler Mars Plastic Erasers 5-Pack",
     "Staedtler Mars Plastic Erasers are precision erasers that cleanly remove pencil "
     "marks without smearing or tearing paper. The PVC-free plastic formula is gentle "
     "on paper surfaces. Erases cleanly to a straight edge for crisp corrections. "
     "Includes protective paper sleeve to prevent soiling. "
     "Suitable for all graphite and colour pencils. Ideal for drafting, "
     "sketching, and school use. 5-pack value set.",
     "Staedtler Mars plastic eraser 5 pack"),

    (369, 'OFF-BNKR-SBOX-029', 49.99, 0.16, 0.46, 260,
     "Bankers Box Stor/File Storage Boxes, Letter/Legal, 12-Pack",
     "Bankers Box StorFile Storage Boxes Letter Legal 12-Pack",
     "Bankers Box Stor/File Storage Boxes are built with SmoothMove technology — a "
     "patented construction featuring reinforced corners and bottom panels for superior "
     "stacking strength. Fits both letter and legal size hanging folders. "
     "Premium-strength box resists moisture and crushing. "
     "Quick-lock bottom requires no tape for assembly. "
     "Liftoff lid with finger holes for convenient access. "
     "12-pack provides enough boxes for a full filing project.",
     "Bankers Box Stor File storage boxes letter legal 12 pack"),

    (370, 'OFF-SCOT-LAMN-030', 34.99, 0.17, 0.47, 280,
     "Scotch Thermal Laminator, 9-Inch Wide, with 30 Letter-Size Pouches",
     "Scotch Thermal Laminator 9-Inch with 30 Letter-Size Pouches",
     "Scotch Thermal Laminator protects and preserves important documents, photos, "
     "menus, ID cards, and more with a professional laminated finish. "
     "Auto-Sense Technology automatically selects the correct heat setting. "
     "9-inch wide feed accommodates letter and legal size documents. "
     "Includes 30 letter-size laminating pouches to get started. "
     "Warms up in under 4 minutes. Anti-jam technology prevents paper from "
     "getting stuck. Built-in pouch holder for storage.",
     "Scotch thermal laminator 9 inch with 30 letter-size laminating pouches"),

    (371, 'OFF-FLWL-STAPN-031', 15.99, 0.18, 0.50, 640,
     "Fellowes Standard Staples, 1/4 in, 5000-Pack, 10 Boxes of 500",
     "Fellowes Standard Staples 1-4 in 5000-Pack 10 Boxes",
     "Fellowes Standard Staples are precision-engineered for jam-free stapling in all "
     "standard desktop staplers. The 1/4-inch leg length is the most widely used size "
     "for stapling up to 20 sheets. Chisel-point tips pierce paper cleanly for a "
     "professional finish. Compatible with all staplers that accept 26/6 staples "
     "including Swingline, Bostitch, and Staples brand staplers. "
     "5000 staples total (10 strips of 500 per box).",
     "Fellowes standard staples 1/4 inch 5000 pack 10 boxes"),
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
    w('-- INSERT 31 best-selling Office Supplies products + pricing + images')
    w(f'-- Generated: {NOW[:10]}')
    w('-- Products  : 31 rows  (product_number 341-371)')
    w('-- Pricing   : 93 rows  (Retail + Promo + Wholesale per product)')
    w('-- Images    : 155 rows (5 images per product)')
    w('-- Category  : Office Supplies  (cdcbd1da-11a2-497a-bc1c-99ff2cd440ec)')
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
        WHERE c.category_name = 'Office Supplies' AND p.product_number BETWEEN 341 AND 371
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
        WHERE p.product_number BETWEEN 341 AND 371
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
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 341 AND 371')
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
        WHERE p.product_number BETWEEN 341 AND 371
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
    w('  SELECT product_id FROM products WHERE product_number BETWEEN 341 AND 371')
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
    cat_dir = "Office Supplies"
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
    """, (product_id, prod_num, name, sku, desc, OFFICE_CAT_ID, stock))
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
    cat_dir    = "Office Supplies"
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
