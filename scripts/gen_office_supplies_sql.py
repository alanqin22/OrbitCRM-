"""Generate sql/insert_31_office_supplies.sql without DB connection."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from urllib.parse import quote

OFFICE_CAT_ID = 'cdcbd1da-11a2-497a-bc1c-99ff2cd440ec'
NOW = '2026-04-04 05:00:00+00'
CAT_DIR = 'Office Supplies'
SQL_OUT = r'D:\a\crm_agent\sql\insert_31_office_supplies.sql'

PRODUCTS = [
    (341, 'OFF-HP-PAPR-001', 12.99, 0.18, 0.50, 1200,
     'HP Printer Paper 8.5x11, Ream of 500 Sheets',
     'HP Printer Paper 8.5x11 Ream 500 Sheets',
     "HP Printer Paper delivers reliable, jam-free printing for everyday office and home use. "
     "The 8.5 x 11-inch, 20 lb / 75 gsm paper works with all inkjet and laser printers, "
     "copiers, and fax machines. Acid-free for longer-lasting documents. Bright white "
     "ColorLok technology ensures vivid colours, darker blacks, and faster drying for "
     "professional-quality results. 500 sheets per ream."),
    (342, 'OFF-POST-NOTE-002', 14.99, 0.18, 0.50, 850,
     'Post-it Notes, 3x3 in, Canary Yellow, 12-Pack (100 Sheets/Pad)',
     'Post-it Notes 3x3 Canary Yellow 12-Pack',
     "Post-it Notes are the original self-stick removable notes. The iconic canary yellow "
     "colour is the most recognized note colour in the world. Each pad contains 100 sheets "
     "that stick and restick without leaving residue. Perfect for reminders, messages, "
     "and desk organisation. 12-pack provides great value for office and home. "
     "Works on most surfaces including glass, painted walls, and paper."),
    (343, 'OFF-SHRP-MARK-003', 18.99, 0.18, 0.50, 680,
     'Sharpie Permanent Markers, Fine Point, Assorted Colors, 24-Pack',
     'Sharpie Permanent Markers Fine Point Assorted 24-Pack',
     "Sharpie Permanent Markers deliver bold, precise lines on almost any surface - paper, "
     "plastic, metal, glass, and more. The fine point tip is ideal for writing, labelling, "
     "and drawing. Fade-resistant and water-resistant ink stands up to daily use. "
     "Quick-drying formula reduces smearing. This 24-pack includes a variety of colours "
     "for colour-coding files, projects, and presentations."),
    (344, 'OFF-BIC-BPEN-004', 9.99, 0.18, 0.50, 1100,
     "BIC Cristal Xtra Smooth Ball Pen, Medium 1.0mm, Black, 20-Pack",
     'BIC Cristal Xtra Smooth Ballpoint Pen Black 20-Pack',
     "BIC Cristal Xtra Smooth Ballpoint Pens are the world's best-selling pen, renowned "
     "for their smooth, consistent writing performance. The 1.0mm medium tip produces a "
     "clean, clear line every time. The transparent barrel lets you see the ink level. "
     "Tungsten carbide ball for smooth ink flow. Non-smear, non-smudge ink. "
     "20-pack value set for home and office use."),
    (345, 'OFF-PILOT-GPEN-005', 19.99, 0.18, 0.48, 720,
     'PILOT G2 Premium Gel Ink Rollerball Pens, Fine Point 0.7mm, Black, 12-Pack',
     'PILOT G2 Gel Ink Rollerball Pen Black Fine Point 12-Pack',
     "PILOT G2 Pens deliver a smooth, comfortable writing experience with premium gel ink "
     "that glides effortlessly across paper. The retractable design with rubberized grip "
     "provides all-day writing comfort. Refillable cartridge for long-lasting value. "
     "The 0.7mm fine point produces crisp, precise lines. Consistent ink flow prevents "
     "skipping and blotching. America's #1 selling gel ink pen brand. 12-pack."),
    (346, 'OFF-SCOT-TAPE-006', 12.99, 0.18, 0.50, 930,
     'Scotch Magic Tape, 3/4 in x 1000 in, 6-Pack',
     'Scotch Magic Tape 3-4 in x 1000 in 6-Pack',
     "Scotch Magic Tape is virtually invisible on paper, making it ideal for wrapping gifts, "
     "repairing torn documents, and everyday office tasks. The matte finish makes it "
     "writable with pen, pencil, or marker. Repositionable without tearing. "
     "Leaves no residue when removed cleanly from most surfaces. "
     "This 6-pack provides long-lasting value. Each roll is 3/4 in x 1000 in."),
    (347, 'OFF-SWIN-STPLR-007', 24.99, 0.18, 0.48, 460,
     'Swingline Stapler, Heavy Duty, Desktop, 25 Sheet Capacity, 1000 Staples Included',
     'Swingline Heavy Duty Desktop Stapler 25 Sheet 1000 Staples',
     "Swingline Heavy Duty Desktop Stapler handles up to 25 sheets at once with ease. "
     "The jam-resistant design prevents frustrating misfeeds. Top-loading mechanism "
     "makes refilling quick and simple. Low-force stapling reduces hand fatigue for "
     "high-volume use. Includes 1000 standard 26/6 staples to get started. "
     "Durable metal construction for long-lasting performance. Works with standard and "
     "cartridge staples."),
    (348, 'OFF-AVRY-LABL-008', 21.99, 0.18, 0.48, 540,
     'Avery Easy Peel White Mailing Labels for Laser Printers, 1 x 2-5/8 in, 750 Labels',
     'Avery Easy Peel White Labels Laser 1x2-5-8 in 750 Labels',
     "Avery Easy Peel White Labels feature a special EasyPeel strip that reveals the label "
     "edge for clean, easy removal from the sheet. Permanent adhesive bonds securely to "
     "envelopes, packages, and files. Works with all laser printers for crisp, professional "
     "results. 30 labels per sheet on standard 8.5x11 paper. Use Avery Design and Print "
     "templates for easy customization. 750 labels total."),
    (349, 'OFF-MEAD-NTBK-009', 18.99, 0.18, 0.50, 620,
     'Mead Spiral Notebooks, 1-Subject, College Ruled, 70 Sheets, 5-Pack',
     'Mead Spiral Notebooks College Ruled 70 Sheets 5-Pack',
     "Mead Spiral Notebooks feature durable covers that protect pages from everyday wear "
     "and tear. College-ruled lines provide adequate space for neat, organized notes. "
     "Perforated pages tear out cleanly without ragged edges. The spiral binding lies flat "
     "when open and allows the notebook to fold completely back. "
     "70 sheets (140 pages) per notebook. This 5-pack provides excellent value for "
     "students and professionals."),
    (350, 'OFF-EXPO-DRYM-010', 16.99, 0.18, 0.48, 580,
     'EXPO Low-Odor Dry Erase Markers, Chisel Tip, Assorted Colors, 8-Pack',
     'EXPO Low-Odor Dry Erase Markers Chisel Tip Assorted 8-Pack',
     "EXPO Low-Odor Dry Erase Markers deliver vibrant, bold colour on whiteboards with "
     "a low-odor formula that is better for enclosed spaces. The chisel tip creates both "
     "broad and fine lines for versatile marking. Easy-to-erase - wipe clean with a "
     "dry eraser or cloth. Ink resists drying out if cap is left off for up to 7 days. "
     "This 8-pack includes black, blue, red, green, purple, orange, brown, and yellow."),
    (351, 'OFF-PNDX-HFLD-011', 19.99, 0.18, 0.48, 490,
     'Pendaflex Hanging File Folders, Letter Size, Assorted Colors, 25-Pack',
     'Pendaflex Hanging File Folders Letter Assorted Colors 25-Pack',
     "Pendaflex Hanging File Folders keep your desk and drawers organised with colour-coded "
     "filing. The reinforced top rail and frame rods are pre-assembled for easy setup. "
     "Scored for 2-inch expansion. Includes clear plastic tabs and white inserts for "
     "custom labelling. Made from recycled materials. Works with standard file cabinet "
     "drawers. Letter size (8.5 x 11 in). 25-pack in assorted colours."),
    (352, 'OFF-3MCM-STPS-012', 22.99, 0.18, 0.48, 410,
     'Command Large Picture Hanging Strips, 14 Pairs',
     'Command Large Picture Hanging Strips 14 Pairs',
     "Command Large Picture Hanging Strips let you hang pictures and frames without nails, "
     "holes, or marks on your walls. The strong adhesive holds securely and removes cleanly "
     "without damaging paint or surfaces. Holds up to 3.6 kg (8 lb) per pair. "
     "Each pair uses two interlocking strips for a firm connection. Ideal for frames, "
     "canvases, and large photos. Works on smooth, finished walls, glass, tile, and metal. "
     "14 pairs included."),
    (353, 'OFF-ACCO-BNDR-013', 29.99, 0.18, 0.48, 380,
     'ACCO 1-Inch 3-Ring View Binder with D-Ring, White, 6-Pack',
     'ACCO 3-Ring View Binder 1-Inch D-Ring White 6-Pack',
     "ACCO View Binders feature a clear overlay on front, back, and spine to customize with "
     "inserts for professional presentation. The heavy-duty D-ring holds more pages and "
     "prevents rings from snagging. 1-inch capacity holds approximately 200 sheets. "
     "Durable polypropylene cover resists stains, tears, and spills. "
     "Acid-free for document preservation. This 6-pack provides great value "
     "for office and school use."),
    (354, 'OFF-ARTZ-CLPN-014', 24.99, 0.18, 0.48, 350,
     'Arteza Colored Pencils, Set of 48 Assorted Colors, Pre-Sharpened',
     'Arteza Colored Pencils Set of 48 Assorted Pre-Sharpened',
     "Arteza Colored Pencils feature a soft, pigment-rich core that blends and layers "
     "smoothly for vibrant results. The pre-sharpened tips are ready to use right out "
     "of the box. Break-resistant leads with superior colour saturation. "
     "Ideal for adult colouring books, sketching, illustration, and classroom use. "
     "Triangular barrel prevents rolling. Each set includes 48 unique colours "
     "ranging from soft pastels to vivid brights."),
    (355, 'OFF-BROT-LBMK-015', 39.99, 0.16, 0.46, 290,
     'Brother P-Touch PTD210 Label Maker with 1 Tape Cassette',
     'Brother P-Touch PTD210 Label Maker with Tape Cassette',
     "Brother P-Touch PTD210 Label Maker creates professional-quality labels for the home "
     "and office. Choose from 14 font sizes, 10 font styles, and multiple frames and "
     "symbols. One-touch auto format keys make labelling quick and easy. The 2-line display "
     "shows your text as you type. Battery-powered for cord-free use. Compatible with all "
     "TZ and TZe tape cassettes 3.5mm to 18mm wide. Includes one black-on-white TZ tape."),
    (356, 'OFF-QRTT-WBRD-016', 49.99, 0.16, 0.46, 240,
     'Quartet Magnetic Dry-Erase Whiteboard, Melamine, 17 x 23 Inch',
     'Quartet Magnetic Dry-Erase Whiteboard Melamine 17x23 Inch',
     "Quartet Magnetic Whiteboard features a melamine surface that is compatible with dry "
     "erase markers and magnets for versatile use. Sturdy aluminum frame provides a "
     "professional look while protecting the edges. Wall-mounting hardware included. "
     "17 x 23 inch size is ideal for home offices, dorm rooms, and small business spaces. "
     "Ghost-resistant surface ensures clean erasing. Use magnets to hold notes and documents."),
    (357, 'OFF-XACT-PNSH-017', 19.99, 0.18, 0.50, 420,
     'X-ACTO Classic Manual Pencil Sharpener with Receptacle',
     'X-ACTO Classic Manual Pencil Sharpener with Receptacle',
     "X-ACTO Classic Manual Pencil Sharpener delivers the reliable, sharp points "
     "professionals demand. The self-cleaning mechanism keeps the blade sharp longer. "
     "Built-in shavings receptacle catches debris for mess-free sharpening. "
     "Suction cup base keeps the sharpener firmly in place. "
     "Accommodates standard and jumbo pencils. Durable all-metal construction "
     "built to last through years of daily use. Table-mount compatible."),
    (358, 'OFF-SMAD-FLDR-018', 29.99, 0.18, 0.48, 330,
     'Smead Manila File Folders, Letter Size, 1/3 Cut, 100-Pack',
     'Smead Manila File Folders Letter 1-3 Cut 100-Pack',
     "Smead Manila File Folders are made from sturdy, heavyweight stock for durable "
     "document storage. The 1/3 cut tabs are positioned at the left, center, and right "
     "for easy labelling and visibility in file drawers. Scored for 3/4-inch expansion. "
     "Letter size (8.5 x 11 in) works with standard file cabinets. "
     "Acid-free for long-term document preservation. "
     "100-pack provides exceptional value for busy offices."),
    (359, 'OFF-WSTC-RULR-019', 9.99, 0.18, 0.50, 700,
     'Westcott 12-Inch Stainless Steel Ruler with Non-Slip Cork Base',
     'Westcott 12-Inch Stainless Steel Ruler Non-Slip Cork Base',
     "Westcott 12-Inch Stainless Steel Ruler features clear, accurate measurements in "
     "both inches (1/16 increments) and centimetres (1mm increments). The non-slip cork "
     "backing prevents sliding for precise measurement and straight-edge cutting. "
     "Durable stainless steel construction resists bending and warping. "
     "Beveled edge design reduces ink smearing when used with drafting pens. "
     "Suitable for use with rotary cutters and craft knives."),
    (360, 'OFF-AVRY-DIVD-020', 19.99, 0.18, 0.48, 480,
     'Avery 5-Tab Dividers for 3-Ring Binders, Insertable, 24 Sets',
     'Avery 5-Tab Binder Dividers Insertable 24 Sets',
     "Avery Insertable Dividers make it easy to organize binders and reference materials. "
     "The clear tabs allow for customizable labels - simply insert your own labels "
     "for a professional, personalized look. Reinforced holes prevent tearing. "
     "Works with Avery and other standard label formats. Prepunched for use in "
     "3-ring binders. 5 tabs per set, 24 sets total (120 dividers). Acid-free and archival-safe."),
    (361, 'OFF-LRLL-TRAY-021', 24.99, 0.18, 0.48, 360,
     'Lorell Mesh Desktop Document Tray, Letter Size, Black',
     'Lorell Mesh Desktop Document Tray Letter Size Black',
     "Lorell Mesh Desktop Document Tray keeps your workspace tidy by corralling loose "
     "papers, files, and mail in one place. The open-mesh design lets you quickly "
     "identify contents without lifting papers. Stackable design allows multiple "
     "trays to be added vertically as your needs grow. "
     "Non-slip rubber feet protect your desk surface. "
     "Letter size holds 8.5 x 11 in documents. Durable black steel mesh construction."),
    (362, 'OFF-ROLD-BCRD-022', 34.99, 0.17, 0.47, 210,
     'Rolodex Wood Tones Desktop Business Card File, Holds 250 Cards',
     'Rolodex Wood Tones Desktop Business Card File 250 Cards',
     "Rolodex Wood Tones Business Card File brings a classic, professional look to your "
     "desktop. The rotating design provides quick access to all 250 business cards. "
     "Alphabetical index tabs help you find contacts in seconds. "
     "Includes 250 sleeves and A-Z index cards. The rich wood-tone finish complements "
     "traditional and modern office decor. Durable construction for lasting "
     "organisation. Ideal for reception desks and executive offices."),
    (363, 'OFF-CAMB-MNTBK-023', 16.99, 0.18, 0.50, 440,
     'Cambridge Business Notebook, 1-Subject, Meeting Planner, 8.5 x 11, 80 Sheets',
     'Cambridge Business Notebook Meeting Planner 8.5x11 80 Sheets',
     "Cambridge Meeting Planner Notebook helps you stay organised during meetings with "
     "a structured format that prompts you to capture key information: attendees, "
     "objectives, action items, and follow-ups. The twin-wire binding opens flat "
     "for comfortable writing. Micro-perforated pages tear out cleanly. "
     "Heavyweight covers protect against daily wear. 80 ruled sheets "
     "(160 pages). Letter size, 8.5 x 11 in."),
    (364, 'OFF-HP67X-CART-024', 39.99, 0.15, 0.45, 310,
     'HP 67XL Black High Yield Original Ink Cartridge',
     'HP 67XL Black High Yield Original Ink Cartridge',
     "HP 67XL Black High Yield Ink Cartridge delivers up to 480 pages per cartridge - "
     "3x more pages than the standard cartridge. Original HP ink provides reliable, "
     "high-quality printing for documents and everyday tasks. Designed for HP DeskJet, "
     "ENVY, and ENVY Inspire printers. Smart chip ensures precise ink tracking and "
     "low-ink alerts. Fade-resistant ink keeps documents looking great for decades. "
     "Easy drop-in installation."),
    (365, 'OFF-CANN-PRNT-025', 89.99, 0.15, 0.45, 180,
     'Canon PIXMA MG3620 Wireless All-In-One Color Inkjet Printer',
     'Canon PIXMA MG3620 Wireless All-In-One Color Inkjet Printer',
     "Canon PIXMA MG3620 Wireless All-In-One Inkjet Printer lets you print, copy, "
     "and scan wirelessly from anywhere in your home or office. Auto Duplex Printing "
     "automatically prints on both sides of the page, saving paper and money. "
     "Print from your smartphone or tablet using the Canon PRINT app or Apple AirPrint. "
     "Maximum print resolution: 4800 x 1200 dpi for sharp, vivid results. "
     "Quiet mode for undisturbed printing. Compatible with iOS and Android."),
    (366, 'OFF-AVRY-BTAB-026', 14.99, 0.18, 0.50, 590,
     'Avery Big Tab Insertable Dividers, 8-Tab, 3 Sets',
     'Avery Big Tab Insertable Dividers 8-Tab 3 Sets',
     "Avery Big Tab Insertable Dividers feature extra-wide tabs that are 50% bigger than "
     "standard tabs for maximum visibility in binders. The clear tabs allow you to "
     "insert custom labels for a personalized, professional look. "
     "Reinforced holes prevent tearing with heavy use. "
     "Works with most laser and inkjet printers for easy label printing. "
     "8 tabs per set, 3 sets total (24 dividers). Letter size, compatible with "
     "all standard 3-ring binders."),
    (367, 'OFF-POST-FLAG-027', 12.99, 0.18, 0.50, 750,
     'Post-it Flags, Assorted Bright Colors, 140 Flags/Pack',
     'Post-it Flags Assorted Bright Colors 140 Flags',
     "Post-it Flags stick and restick without tearing pages, making them perfect for "
     "bookmarking, flagging, and highlighting important information in documents and books. "
     "The bright assorted colours are ideal for colour-coding chapters, sections, or "
     "priority levels. Tabs extend beyond the page for easy retrieval. "
     "Repositionable without leaving residue. 140 flags per pack in "
     "assorted bright colours including pink, orange, yellow, green, and blue."),
    (368, 'OFF-STDR-ERSR-028', 8.99, 0.18, 0.50, 920,
     'Staedtler Mars Plastic Erasers, 5-Pack',
     'Staedtler Mars Plastic Erasers 5-Pack',
     "Staedtler Mars Plastic Erasers are precision erasers that cleanly remove pencil "
     "marks without smearing or tearing paper. The PVC-free plastic formula is gentle "
     "on paper surfaces. Erases cleanly to a straight edge for crisp corrections. "
     "Includes protective paper sleeve to prevent soiling. "
     "Suitable for all graphite and colour pencils. Ideal for drafting, "
     "sketching, and school use. 5-pack value set."),
    (369, 'OFF-BNKR-SBOX-029', 49.99, 0.16, 0.46, 260,
     'Bankers Box Stor/File Storage Boxes, Letter/Legal, 12-Pack',
     'Bankers Box StorFile Storage Boxes Letter Legal 12-Pack',
     "Bankers Box Stor/File Storage Boxes are built with SmoothMove technology - a "
     "patented construction featuring reinforced corners and bottom panels for superior "
     "stacking strength. Fits both letter and legal size hanging folders. "
     "Premium-strength box resists moisture and crushing. "
     "Quick-lock bottom requires no tape for assembly. "
     "Liftoff lid with finger holes for convenient access. "
     "12-pack provides enough boxes for a full filing project."),
    (370, 'OFF-SCOT-LAMN-030', 34.99, 0.17, 0.47, 280,
     'Scotch Thermal Laminator, 9-Inch Wide, with 30 Letter-Size Pouches',
     'Scotch Thermal Laminator 9-Inch with 30 Letter-Size Pouches',
     "Scotch Thermal Laminator protects and preserves important documents, photos, "
     "menus, ID cards, and more with a professional laminated finish. "
     "Auto-Sense Technology automatically selects the correct heat setting. "
     "9-inch wide feed accommodates letter and legal size documents. "
     "Includes 30 letter-size laminating pouches to get started. "
     "Warms up in under 4 minutes. Anti-jam technology prevents paper from "
     "getting stuck. Built-in pouch holder for storage."),
    (371, 'OFF-FLWL-STAPN-031', 15.99, 0.18, 0.50, 640,
     'Fellowes Standard Staples, 1/4 in, 5000-Pack, 10 Boxes of 500',
     'Fellowes Standard Staples 1-4 in 5000-Pack 10 Boxes',
     "Fellowes Standard Staples are precision-engineered for jam-free stapling in all "
     "standard desktop staplers. The 1/4-inch leg length is the most widely used size "
     "for stapling up to 20 sheets. Chisel-point tips pierce paper cleanly for a "
     "professional finish. Compatible with all staplers that accept 26/6 staples "
     "including Swingline, Bostitch, and Staples brand staplers. "
     "5000 staples total (10 strips of 500 per box)."),
]

PIDS = [
    'f7037bb7-30df-4fb6-9c00-4ef21a3ff0ac','f12bc5e3-2642-4cdd-8135-cc3ab769306b',
    '5f85b0e7-57fe-4c55-a1c4-08594beaf950','33ef4c54-0988-4e68-8e77-b8c95016277a',
    '16c4abdf-9444-4cdd-b2f4-5b6c598cbd8e','ec6691ae-ecd3-4539-a172-e65e4e301636',
    'ef85fe82-66d6-42c2-b5f1-90cd8e646f90','723e72f3-93bc-41d2-b660-1249127023cf',
    'aa238e07-8d3a-4b06-9b91-6085eb1bad50','ee436c95-db44-4f22-82ab-3eb3c8358003',
    '95a2a9b2-95f5-483f-b1f9-50ed3a505e1c','86c606cd-be2f-40a7-bc26-4f9acd86cdff',
    'd7b129d2-bb18-4c90-8575-ab18b3e94c1f','4fd8204a-139f-46be-ba6f-43439e59c78c',
    'f4e5651f-b276-4c2d-a2a8-81f244fd32f0','3a472b00-2685-4e2a-b539-42101d9f5951',
    '3d73c779-ae75-4455-8b03-203565ca40e5','03ddbbff-eaf3-4b02-b554-f5b3b778d299',
    '66f5d69c-a864-4a9f-9639-8576a08b8c37','79dae83b-ea74-4b17-881b-458a30235843',
    '859ae67c-6467-4cd8-807a-a967e3636fb6','5c99cbd8-9b5f-425e-ad9c-bc5f34694ca3',
    '5383a506-6bd8-4e38-bcfb-852b7f1ab361','6091c8c2-b479-4240-ade1-81c134bcb4fa',
    '07cada33-c059-4347-888c-0bbe17af3676','00f29284-4dc9-47bf-bb20-b163df932112',
    '0801104f-f431-469c-b5cc-c1d6dd932267','fa8e306f-8bbd-4778-ba96-695f95bcef37',
    '65022eb7-567f-40f4-9196-fd1a41171059','d1b726f1-5228-4e0a-b1af-d54549ee3cd2',
    '83d3f41b-914e-4ce7-a403-9cb22fec3343',
]

PPIDS = [
    '678d1e0f-5b04-405d-ac38-17f1c4494853','56661f84-9d19-409a-82c2-9927c9424e43','cccb610b-67cd-45fd-a23b-a375c88b092c',
    '5aeba5c9-e1c4-4236-8f7e-bb08db959694','1bea7dbe-f59e-4ab4-a8ed-fa39c902ea40','bc21ceb9-1e47-47a4-addd-b0154ef72193',
    '2653d11c-498a-4795-a1c5-06bab3e45bab','91fad071-0df7-4225-8ae8-5c7319f1ae15','d45210f3-a9b7-47c2-8470-01443375f329',
    '493e16ae-36e9-48c2-a8cd-2cae8946df19','c89cc176-d99f-4480-9f56-417b85a88174','c09a6a3a-139f-484a-8e19-79f25961e292',
    'c4b27ecf-4dce-49ea-8017-9200b718d4a5','03e69d4a-acb8-4f4b-986b-261ec29c4c80','faa900e4-d4df-4b69-814c-c2f805837316',
    'ce0d9139-d4f1-41f0-9ae3-6de87b90f6b2','7bf33941-eaa9-481c-965d-4e7b2068144c','58264567-6c17-4b31-ba2c-f54ca0df84f9',
    '42941d26-67ff-42ba-babb-230b7e23519d','8f520dd1-db90-4e30-9c90-95a59bf68866','eee85e50-bc04-4601-942c-36973b3ad9af',
    'e4067b74-66db-4a09-b865-f2dcfd0c7645','a032300c-02f2-49c6-863d-a2a349e77f4c','7756b83d-b79f-43f9-bc66-f6d831cfb122',
    '161832b0-43e9-4b13-87ad-3ae46f81299b','5f176450-36e9-4f6f-9ebb-44fa1767b431','bbe519bf-ef8d-413b-8205-70a83b96e0aa',
    'b37f185e-676f-4545-b9b2-19436287836b','ecfcceb5-e3b3-4f87-bf44-2d6dd2b7c3f6','ce2d7b03-a801-4a58-b1e5-ba9b4e69826a',
    'a9f1bec0-1d29-408b-95f9-f0ea2b75e245','31fd46c0-d8ea-4335-9808-55fbfcb87b09','72d5cb18-890c-4688-9909-d553221ff5a4',
    'fe6cd8f4-dbd4-4217-9b4f-0bc8beace0ff','cdfdbdb9-404e-4d78-9034-9bd6e28f0004','788de9be-4573-4447-81fe-83525b131b67',
    '798660d0-d213-4f9e-ac2e-fa049c303c87','30bf2d0a-9c19-4dd8-81c5-0932657d0311','4be51d5b-eba4-401c-b670-3514bab2d4ae',
    'f50f43df-b4ee-40f9-b529-25dc0f0aac32','e120c3d9-2a14-4455-bdc8-4f71cafe835c','ee2718a4-a5d9-4dd1-bd95-8e70de19b450',
    'ec1a2617-8a67-4c17-a38c-667b08bd109c','40342182-d10e-45c8-b97d-c25c1dbf07de','91b2e90e-dfa2-41dc-9770-f01be1a6a308',
    '434fb5e5-ed89-4755-af69-32ddfd5f916b','3a785185-7fd3-43e3-8c22-6221e5deb400','bcc463bf-6dbf-4fbc-8313-83514d3f6a11',
    '01075f7c-09b2-4ca3-95d0-82e3b0c803b2','55e09932-4563-4266-9034-08ccf1bd4a84','fcb47434-292f-48e9-aa8e-1e8627990cc6',
    'be957c73-71eb-4f62-bb71-23578d1c8313','aef1c401-d484-423a-ae99-8004531a190d','69e90710-bb8d-43ac-905e-4c336b34a3a7',
    '63d2be72-9f69-4283-a077-1d01c6f482c6','1fe4cdec-b2d2-4597-9ef6-1d3dd022c1bd','29734021-3a04-414b-9120-0d6ee6230b65',
    'f94b4e9b-186d-4a87-885e-6a56a2bb9ad6','cf6aa31f-5187-4f89-a86d-7142af80db8e','084ab2fa-99e8-4235-ba18-561146333150',
    'd64d9a12-86f5-4fd8-a131-d43fbd94efcb','aaa10ffc-f0b9-44cc-b780-3a8327c8166f','84ed3c98-4a46-44c5-bf49-802e46dbd837',
    '55c8dd5c-c2b4-4faf-bb40-3c1a920f2ca1','2e0f80b5-5ea9-4b02-a019-d5398658dd65','f75f4aff-5cad-4bca-a659-6669db30930a',
    'c988f138-1c9e-48b9-948f-8e2b19c74334','15260439-5464-4638-89c1-04a36c4e28a8','cf333c6b-d881-47dc-b643-fe497a10d274',
    '15375e9a-6cf6-4972-967f-8cd3210d8ef4','c2d1b214-5b29-4dec-a50a-f96ffa2a1d7f','680801a6-158d-41f1-9f7c-97074fda8192',
    '676f0f3c-1fd1-471d-83d5-17d02947acac','36cbcce2-ab0c-44e3-9684-647e4d851107','f89b965f-0186-4e73-baf7-b96720604d9e',
    '2f66a854-782a-4d63-9609-3b6cd3c1689a','43c90c6c-7af3-47b2-b137-f550cbc67419','88e8d96e-66b9-4b83-bfcd-651dcdeab26a',
    '5c3994a6-751d-444e-9be6-b15db2642f25','a62204cd-aff2-4125-a18f-432acb77395b','8ce04d7e-1f85-4740-a02e-8142639a3caa',
    '2f1d0233-9994-4d3e-b328-cc06d87f143e','eae50397-d467-4eea-b461-5c91dffebaec','8baa4305-20ec-4d94-89bb-c0557631bde0',
    '3a2d8583-012f-4f2a-a4eb-e7cbfd54a699','5c641581-b2a7-4676-ab8b-3b1a79851f2c','77d36eaa-585a-4658-966b-44fe6a20f587',
    'cc7eb0f2-f5a4-4ef8-b9a3-1550aacce584','f221df32-3c4b-496f-83b6-9f6c8a2e8be6','f5a16d10-85b6-49b3-b247-a0ffd6407e59',
    'e36e9812-2e31-45a1-8ffc-2ae78df58edc','1a9331f6-d595-4db0-854a-66b9be97f771','21b8f615-7e0d-49b2-bd90-c716b8268173',
]

IMIDS = [
    'df7ca38a-c736-489d-9437-aab282e73b22','0c0c2a46-7aa3-4cd7-b641-b4e3a11ceb02','4c01e621-78f8-4860-93fc-42a1264775c5','9ffb41df-d3e0-4ca5-abdf-70b20f154370','584de597-3b36-4b51-a7f1-55d6b94570d9',
    '2fbdce7e-6fcd-4303-b6a8-4f7ad2f07b8e','e7250994-8c10-4ec5-83d8-f8d7332e7f75','61730d4d-5ffb-4ef1-a45e-4e76a46ebe73','c0ccff19-d5e5-4c31-b385-84ad10b0a433','7f992de9-1a51-4784-b010-a81be771b174',
    'df2d2c08-8b5b-4b48-ad1b-4367e5fc59eb','c42a5fe6-4107-4370-9465-d5a3bb277d78','7207144f-7220-4426-ad62-d19c081cd191','906fda2f-568e-46b6-89d9-60d027596a73','4523d85d-1a89-421d-ad1a-bf3f9f9a85f8',
    '1a75cc42-fca6-47f4-a63d-93fefd8b762e','85ee29b6-31ff-4ef8-9f7d-c82d72ce2fa6','b42f8d01-62c1-418a-93e1-8af3a4cd6df3','357169ab-c41f-4c44-a19e-3a92e494673c','712f76f3-4bd4-473d-b21c-6d40044f4306',
    '78018762-086e-4cc0-9018-fbc28dcbbeca','0c3a162a-75e1-4918-abe8-714cbadfac50','c6415af0-3527-4665-b9d1-ade60d29ab56','fa6ae42b-4b96-483c-9b1d-d1647530297f','41fa9d62-ff8d-46f1-9c76-9ed99e63bd3e',
    'b549a624-2c71-4e74-b3ee-04105a0bc8f1','772d76ac-4f86-498c-b4f6-efd398c0c25e','9bc81a10-3f55-437c-8361-b98502918cf0','6753fa25-a312-4162-8c5d-d9cbc02ccadc','ab8ca2a9-2c2d-4c38-8b09-8c0b032e10ce',
    'eb6af23f-971d-4b01-b498-514968eceecc','b2ad1048-2a98-4852-90ed-85fab7fa5d98','a1cf19ce-6257-4fa3-85b4-fd1bf0a57949','0b24c052-11bc-47bf-a36a-e6d8d99c6418','960e132c-0a25-4325-b4dc-4a46bed09086',
    '2671ce84-2907-40c7-a430-a1f8ccd4b133','516c41bb-9c24-415c-836e-db92cfeaba91','c27454f0-1041-4b04-b91c-2fcda4525047','9821d91e-1a4c-429d-86f6-57ef3b5621b1','c231e5f0-798a-4bf1-aa2e-5b479d69d27c',
    '645eed44-27c0-46b0-b927-ab0d89cfff97','d73e40d8-66f5-49f3-91d2-5b08fd3be5a1','78453829-eea7-4077-9322-8f6cab71f871','38b44557-aff1-401a-9595-e7cc0140d790','5ba23163-75c3-46fe-b767-2293ea221f14',
    '533668d1-5399-4d7c-9cc5-ac4f0cf06b30','23086b1e-f30a-461b-bf75-ad01f3ebe726','4adad50b-3039-424e-8160-8f7893f99f29','67ccb244-d074-4ba6-8cc7-e198774c292f','f3504959-026e-4bfa-b209-c546f8f2203c',
    'd2b6d77e-5c98-43bd-b3d0-1494aaf2e231','498dd6a4-1aa0-490a-b96d-89b134b43fe0','3568d789-d938-4b9a-8fbe-8fd3f596379e','ba032547-539c-412d-82ad-c43d4e24957a','6289293c-b8ab-48ae-af30-3c9facad35f7',
    'b025fe94-9f59-4620-9c59-d4e2f15fc376','f1a951c5-1a57-406a-85d6-b07729dd25c5','ae070239-6371-4ae7-96de-78ed7821deeb','19331136-457d-4fb4-8196-320299f1e914','5221652c-22f7-40cd-ab03-63c271136692',
    'fb5d2c80-5a63-456c-bee7-cd54757b08a2','c145823b-9a84-44ce-b59a-4d30c2e50d09','7bbf0f80-7795-48dc-9ab4-2db88dce5b64','f980f16d-5428-4f2f-aa99-587cf1531059','348dc931-a43c-4623-b2cd-92497bfafd6e',
    '15f9395c-6b63-4bb4-aa35-f2399946d732','11a2042d-a106-449a-a503-161061024583','41bfad02-e7e7-4de1-9515-f0d14ac2da59','137d1289-0eae-4b76-ba28-fa90f7d0e631','ec66090a-4203-4aa6-882e-fa8fac81e9c0',
    '47ee1e2b-dabd-4987-b50e-4de7d85f0c5d','8e6fe6e6-fdd1-4360-b690-13781dd5170a','1593529e-b6b3-4515-b0a2-48de01f18f7b','9fcb6f7f-be6a-4d7a-adf3-950852b54df9','75816b05-bf92-4018-a293-5149664f0aef',
    '0a89f26a-67d9-47ac-b23e-af8f3e147f11','55f29f85-1764-4a38-8d71-8dba9af88992','844cfb84-df30-43d2-9e3b-2b154c4de0bb','a9635a92-da48-4e3d-81e0-e780ab9e0cad','4d441c67-3c70-42ce-8a12-8ec00ad2867d',
    '96c38d66-ca6b-4933-973e-4e2d2af79d74','582ebf16-2fa5-440c-b3b6-96668de5d232','1fec3037-89c8-4e2c-b70d-b9a95ea53230','fbec3e97-d3b8-47a5-bc74-579233ab64fe','7c971d38-f901-442e-8736-c69c1443a9fb',
    '20574400-915b-4bd6-8025-1e78edc58403','b4138c2a-3963-432b-9582-259bf6a079c1','d00c9223-e67b-4e00-a577-1ca9b9f0b0b7','44a525d1-6a8c-428f-8563-cd74292bcf9a','2bbfdf03-0102-4441-92ff-e17ba049638b',
    '34e28e74-211f-41cb-961d-81daa944e21e','19989bb2-0f12-4481-9648-d3dce8596936','16d610b6-1296-4c2c-be74-30d859ebc03c','20a31d6b-bfbb-48c0-b450-3e83146124e8','852a7856-0637-47cf-81cd-0df4551242ef',
    'a9a0bcd7-2a05-4d44-a346-6dda94120193','cb1c6c0b-2f96-43a7-92cc-5758229e1370','7ac1be80-233a-482a-bb89-9fe3a653f9b4','712ce1ac-f706-4fd2-b7f9-61059ac0da88','b71ae445-ec0e-4a2b-8d83-c5954a1405de',
    'deb15093-24c9-4667-83d4-dd83c8ddd330','873a16e3-12e8-4aa3-9612-d87aa2339c79','eb4fe10f-0820-4d3e-9ef0-79eeaaade1e7','122c1009-aa72-47f0-9bbc-44abb0234f23','732399e4-93e9-4f1f-9a28-dcd42e32a99b',
    'e7e03d83-b1c6-4be6-8281-dd9cdf55abd9','3350750f-e07e-443f-b7e1-ff794cca38cc','e9ea1793-00a9-4b7a-a544-a05d2f3497d1','68b23f65-8181-48d6-bc31-cd54fb7c0fe3','b49f1842-6fbe-4479-ab0d-3a494a807a53',
    '16fc1a25-b1bc-4665-9976-2cd87e081cd0','57fd1d4a-36c1-4d6e-9baf-91f64f8faef9','1dd210d8-7f45-47b8-9936-a4e3bf8ddc9c','30e71446-d4c5-41bb-b924-2ad17cd7dbba','b3b58186-f818-4768-a5e0-df1eb21b2404',
    '41d373e7-ebcf-43b2-8f93-f9d67d563282','8a899fbd-b3f1-4de6-b058-84c20cefc1b2','87b404cb-068b-4d86-a0c6-0c70a52bd57b','82445881-a7b5-4692-b406-be4e750004e3','bc23a24f-5d4d-4dd9-a2d4-7334533cfe86',
    'e67201b9-682a-42ce-b6b0-3d97b50d3cd8','d4ed0f95-577f-466b-ad97-adb09efa616a','d0933a80-f526-4fe6-937a-612690c03c07','dca0ba47-e5db-4295-9771-a85c8262dca8','a6bb4ea7-e04a-474d-be73-497ebba062f4',
    '2a47b180-bed6-4cb7-a164-2a1d4e2a47e7','f2ca60e8-72a9-48de-a437-489c13ac592b','12d795a2-7a63-4496-81e9-cef75947cebd','87d86317-c812-4059-826d-d57d21c7f697','5e43e819-cfc9-491d-b4ae-3c9f5fc86f41',
    'bad5cfea-aaf7-457a-9a31-fda69fd4a39e','f12757c6-f005-44cf-849f-d616e45e8e34','72bdc5eb-750e-4b36-970e-a7f39199b8aa','16cd90c0-eb78-4a8a-8c8f-ea4dec6ff0c1','ce69b8bf-5122-46fa-ab3d-d8e4f17990e1',
    'c77a53e9-c905-47d8-998d-a1481450b8d3','d0927bca-5eaf-4d35-b642-f6028ff66aea','d44374b1-ea83-4b5d-8851-0b687f9c9d62','d56747d9-2e67-40fb-8df6-fc79f494f592','e6391baa-f2d5-4173-ba93-186ad4ff1427',
    '75406897-bbae-4887-86ca-dd4435154638','778e6dd6-39d1-48fd-96c5-450f61c82d64','dfd821c1-9e3a-4bef-87d9-801272bbd2dd','ba5714a6-9c6c-4c34-90b0-34bcef84bd04','83723e2b-71af-4c55-9424-4e6f70a0b82e',
    'a3103e9a-1578-4dc0-8a89-f475d9871511','8beecb7a-79e6-4bbe-8af7-26f7621712b5','2f700fa3-ecb9-40d3-bce9-81854b3531f7','6b14d12e-967c-428f-8461-65f853b12f33','79da0e71-47f3-4c7d-841f-d5d8a162b583',
    'b1d0a898-5058-4b5b-bb0b-0e13fe92e3e9','723648ca-b6f8-4d40-abb2-953052d64c50','078ade9e-9aad-4270-8487-007a0ba403b2','a260f5b4-08d2-4f1e-8ee3-679c828f826e','7cfd4bb9-1673-4bc0-a553-b799f5085ccd',
]


def esc(v):
    if v is None:
        return 'NULL'
    return "'" + str(v).replace("'", "''") + "'"


lines = []
def w(s=''):
    lines.append(s)

w('-- ============================================================')
w('-- INSERT 31 best-selling Office Supplies products + pricing + images')
w('-- Generated: 2026-04-04')
w('-- Products  : 31 rows  (product_number 341-371)')
w('-- Pricing   : 93 rows  (Retail + Promo + Wholesale per product)')
w('-- Images    : 155 rows (5 images per product)')
w('-- Category  : Office Supplies  (cdcbd1da-11a2-497a-bc1c-99ff2cd440ec)')
w('-- Currency  : CAD')
w('-- ============================================================')
w()

# SECTION 1
w('-- ============================================================')
w('-- SECTION 1: products (31 rows)')
w('-- ============================================================')
w()
for i, (num, sku, retail, ws_pct, promo_ratio, stock, name, folder, desc) in enumerate(PRODUCTS):
    pid = PIDS[i]
    w(f'-- [{num}] {name[:72]}')
    w('INSERT INTO products')
    w('  (product_id, product_number, product_name, sku, description,')
    w('   category_id, currency_code, stock_quantity, is_active, is_synthetic, created_at, updated_at)')
    w('VALUES')
    w(f"  ({esc(pid)}, {num}, {esc(name)}, {esc(sku)}, {esc(desc)},")
    w(f"   {esc(OFFICE_CAT_ID)}, 'CAD', {stock}, TRUE, FALSE, {esc(NOW)}, {esc(NOW)})")
    w('ON CONFLICT (sku) DO UPDATE SET')
    w('  product_name   = EXCLUDED.product_name,')
    w('  description    = EXCLUDED.description,')
    w('  stock_quantity = EXCLUDED.stock_quantity,')
    w('  updated_at     = EXCLUDED.updated_at;')
    w()

# SECTION 2
w()
w('-- ============================================================')
w('-- SECTION 2: product_pricing (93 rows)')
w('-- ============================================================')
w()
w('DELETE FROM product_pricing')
w('WHERE product_id IN (')
w('  SELECT product_id FROM products WHERE product_number BETWEEN 341 AND 371')
w(');')
w()
pp_idx = 0
for i, (num, sku, retail, ws_pct, promo_ratio, stock, name, folder, desc) in enumerate(PRODUCTS):
    pid = PIDS[i]
    ws    = round(retail * (1 - ws_pct), 2)
    promo = round(retail - (retail - ws) * promo_ratio, 2)
    for ptype, pval in [('Retail', retail), ('Promo', promo), ('Wholesale', ws)]:
        ppid = PPIDS[pp_idx]; pp_idx += 1
        w(f'-- [{num}] {sku}  {ptype}: ${pval}')
        w('INSERT INTO product_pricing')
        w('  (product_pricing_id, product_id, price_type, price_value, currency_code,')
        w('   is_synthetic, created_at, updated_at)')
        w('VALUES')
        w(f"  ({esc(ppid)}, {esc(pid)}, {esc(ptype)}, {pval}, 'CAD',")
        w(f"   FALSE, {esc(NOW)}, {esc(NOW)});")
        w()

# SECTION 3
w()
w('-- ============================================================')
w('-- SECTION 3: product_image (155 rows)')
w('-- ============================================================')
w()
w('DELETE FROM product_image')
w('WHERE product_id IN (')
w('  SELECT product_id FROM products WHERE product_number BETWEEN 341 AND 371')
w(');')
w()
im_idx = 0
for i, (num, sku, retail, ws_pct, promo_ratio, stock, name, folder, desc) in enumerate(PRODUCTS):
    pid = PIDS[i]
    folder_enc = quote(folder, safe='')
    cat_enc = quote(CAT_DIR, safe='')
    for sort in range(1, 6):
        imid = IMIDS[im_idx]; im_idx += 1
        url = f'https://agentorc.ca/image/{cat_enc}/{folder_enc}/image_{sort}.jpg'
        alt = f'{name} - Image {sort}'
        w(f'-- [{num}] {sku}  sort={sort}')
        w('INSERT INTO product_image')
        w('  (product_image_id, product_id, image_url, sort_order, alt_text, created_at)')
        w('VALUES')
        w(f'  ({esc(imid)}, {esc(pid)}, {esc(url)}, {sort}, {esc(alt)}, {esc(NOW)});')
        w()

with open(SQL_OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Written: {SQL_OUT}')
print(f'Total lines: {len(lines)}')
print(f'Products: {len(PRODUCTS)}, Pricing rows: {pp_idx}, Image rows: {im_idx}')
