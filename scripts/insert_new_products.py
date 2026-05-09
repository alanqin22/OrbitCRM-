import psycopg2, uuid
from urllib.parse import quote

conn = psycopg2.connect(host='shinkansen.proxy.rlwy.net', port=26832, dbname='railway',
                        user='postgres', password='SimKpntYtoGdLWdVsXglunQqHZMHXUfQ')
conn.autocommit = False
cur = conn.cursor()
NOW = '2026-03-27 16:00:00+00'

CAT = {
    'Apparel':            '7632ef73-7a4a-4320-b5d8-a2bb72bd8c03',
    'Grocery':            'fea01756-1ba1-4b38-841f-c6a2b86bb2a6',
    'Home Essentials':    'c346f439-e972-4f0a-8115-f3baa63cc1d8',
    'Office Supplies':    'cdcbd1da-11a2-497a-bc1c-99ff2cd440ec',
    'Personal Care':      'adf36cbb-9243-4a60-96ac-f5998361ed91',
    'Snacks & Beverages': '64c198d3-3bcc-4291-ab8d-7e12abf24b2f',
    'Pet Supplies':       '7fb054a9-5457-4932-9c89-4701da3f1dcc',
}

# (num, cat, sku, retail, ws_pct, promo_ratio, stock, name, folder, desc)
PRODUCTS = [
  (160,'Apparel','APP-HANE-ECOS-014',22.00,0.20,0.42,340,
   "Hanes Men's EcoSmart Fleece Pullover Hoodie Sweatshirt",
   "Hanes Men's EcoSmart Fleece Hoodie Sweatshirt",
   "The Hanes Men's EcoSmart Fleece Hoodie is made from a cotton-blend fleece using up to 5% recycled "
   "polyester from plastic bottles, featuring double-needle stitching throughout for durability. "
   "It includes a front pouch pocket, no-bunch cuffs and waistband, and an adjustable drawstring hood "
   "for a comfortable, casual fit in sizes S-3XL."),

  (161,'Apparel','APP-FRUI-EVER-015',24.97,0.18,0.45,290,
   "Fruit of the Loom Men's Eversoft Cotton Short Sleeve T-Shirts, 6 Pack",
   "Fruit of the Loom Men's Eversoft Cotton T-Shirts Pack of 6",
   "Fruit of the Loom Eversoft T-Shirts are crafted from 100% pre-shrunk soft cotton that stays soft "
   "wash after wash, with a tag-free neck for all-day comfort. "
   "The pack of 6 includes a variety of classic solid colors with ribbed crew neck and double-needle "
   "hemmed sleeves that retain their shape over time."),

  (162,'Grocery','GRO-QUAK-OATS-018',9.98,0.17,0.40,420,
   "Quaker Old Fashioned Rolled Oats, Two 64oz Bags, 90 Servings",
   "Quaker Old Fashioned Rolled Oats 4.52 lb",
   "Quaker Old Fashioned Oats are 100% whole grain rolled oats that cook in 5 minutes on the stovetop, "
   "providing 4g of fiber and 5g of protein per serving with no added sugar or artificial flavors. "
   "Non-GMO Project Verified, this family-size box contains two 64oz bags totaling approximately 90 servings."),

  (163,'Grocery','GRO-NATU-VALY-019',4.29,0.15,0.48,510,
   "Nature Valley Crunchy Granola Bars, Oats 'n Honey, 12 Count (6 Pouches)",
   "Nature Valley Crunchy Granola Bars Oats n Honey 12 Count",
   "Nature Valley Crunchy Granola Bars are made with whole grain oats and real honey, delivering a "
   "satisfying crunch with 17g of whole grains per serving and no artificial colors or flavors. "
   "Each box contains 6 pouches with 2 bars each, a convenient on-the-go snack that is a good source "
   "of calcium and B vitamins."),

  (164,'Grocery','GRO-KELL-SPEC-020',5.48,0.16,0.44,380,
   "Kellogg's Special K Original Breakfast Cereal, Family Size, 18 oz",
   "Kelloggs Special K Original Cereal 18oz",
   "Kellogg's Special K Original is a lightly toasted rice and wheat flake cereal fortified with "
   "8 vitamins and minerals including folic acid, iron, zinc, and B vitamins for a nutritious start. "
   "At just 120 calories per serving with 6g of protein, the 18oz family-size box pairs perfectly "
   "with milk or yogurt."),

  (165,'Home Essentials','HOME-OXO-BOWL-015',39.99,0.20,0.38,175,
   "OXO Good Grips 3-Piece Stainless Steel Mixing Bowl Set",
   "OXO Good Grips 3-Piece Stainless Steel Mixing Bowl Set",
   "The OXO Good Grips 3-Piece Stainless Steel Mixing Bowl Set includes 1.5, 3, and 5-quart bowls, "
   "each with a non-slip base and convenient pour spout for controlled transfers. "
   "The dishwasher-safe brushed stainless steel construction resists staining, and ergonomic soft-grip "
   "handles provide a secure, comfortable hold for all mixing tasks."),

  (166,'Office Supplies','OFF-POST-STIC-019',24.93,0.19,0.41,260,
   "Post-it Super Sticky Notes, 3x3 in, 24 Pads, 90 Sheets/Pad, Canary Yellow",
   "Post-it Super Sticky Notes 3x3 in 24 Pads Canary Yellow",
   "Post-it Super Sticky Notes feature 2x the sticking power of original Post-it Notes, holding firmly "
   "on vertical, low-energy, and curved surfaces without leaving residue. "
   "The 24-pad value pack in classic Canary Yellow provides 2,160 sheets total, ideal for office "
   "reminders, brainstorming, and project planning."),

  (167,'Office Supplies','OFF-SCOT-TAPE-020',15.97,0.17,0.46,215,
   "Scotch Heavy Duty Shipping Packaging Tape, 1.88 in x 38.2 yd, 6 Rolls",
   "Scotch Heavy Duty Shipping Packaging Tape 6 Rolls",
   "Scotch Heavy Duty Shipping Packaging Tape features a strong thick adhesive that seals cartons "
   "securely and resists splitting, even in cold storage conditions down to -20 degrees F. "
   "The 6-roll multipack provides 1.88 inches wide by 38.2 yards per roll of crystal-clear tape, "
   "compatible with all standard handheld tape dispensers."),

  (168,'Personal Care','PC-DOVE-MENS-014',9.97,0.18,0.44,320,
   "Dove Men+Care Body Wash Extra Fresh, 30 fl oz",
   "Dove Men+Care Body Wash Extra Fresh 30 fl oz",
   "Dove Men+Care Extra Fresh Body Wash contains MicroMoisture technology that activates in the shower "
   "to fight skin dryness, leaving skin feeling clean, refreshed, and moisturized rather than tight. "
   "Formulated with a cooling menthol scent and mild dermatologist-recommended cleansers, this 30 fl oz "
   "bottle is free of parabens and suitable for daily use."),

  (169,'Personal Care','PC-HEAD-SHOU-015',12.97,0.20,0.40,285,
   "Head & Shoulders Classic Clean Daily Anti-Dandruff Shampoo, 32.1 fl oz",
   "Head and Shoulders Classic Clean Dandruff Shampoo 32.1 fl oz",
   "Head and Shoulders Classic Clean Shampoo provides 100% flake protection with pyrithione zinc, "
   "clinically proven to control dandruff while gently cleansing and refreshing scalp and hair. "
   "The 32.1 fl oz paraben-free formula is suitable for everyday use on all hair types, leaving hair "
   "clean, smooth, and manageable with a light fresh scent."),

  (170,'Snacks & Beverages','SNK-CELS-WILD-014',19.99,0.17,0.43,390,
   "CELSIUS Sparkling Wild Berry Energy Drink, 12 Fl Oz (Pack of 12)",
   "Celsius Sparkling Wild Berry Energy Drink 12 fl oz Pack of 12",
   "CELSIUS Sparkling Wild Berry is a fitness energy drink clinically proven to accelerate metabolism, "
   "containing 200mg of natural caffeine from green tea extract plus B-vitamins and vitamin C with "
   "no sugar, no aspartame, and no artificial preservatives. "
   "Each 12 fl oz can delivers a refreshing wild berry flavor with only 10 calories."),

  (171,'Snacks & Beverages','SNK-RXBA-CHOC-015',23.99,0.19,0.42,265,
   "RXBAR Chocolate Sea Salt Whole Food Protein Bar, 1.83 oz, 12 Count",
   "RXBAR Chocolate Sea Salt Protein Bar 1.83 oz 12 Count",
   "RXBAR Chocolate Sea Salt bars are made with real whole food ingredients - dates, egg whites, "
   "cashews, and almonds - with no added sugar, soy, dairy, gluten, or artificial additives. "
   "Each 1.83 oz bar delivers 12g of protein and 5g of fiber, making the 12-count box a clean, "
   "convenient snack for pre- or post-workout recovery."),

  (172,'Pet Supplies','PET-PURI-PROP-016',64.98,0.22,0.40,145,
   "Purina Pro Plan High Protein Dog Food, Shredded Blend Chicken & Rice Formula, 35 lb",
   "Purina Pro Plan Shredded Blend Chicken Rice Formula 35 lb",
   "Purina Pro Plan Shredded Blend combines crunchy kibble with tender shredded pieces for a taste "
   "dogs love, with real chicken as the #1 ingredient and live probiotics to support digestive and "
   "immune health. Formulated by Purina scientists and veterinarians, this 35 lb bag provides optimal "
   "protein-to-fat ratio and omega-6 fatty acids for a healthy skin and coat."),

  (173,'Pet Supplies','PET-GREE-ORIG-017',29.98,0.20,0.45,198,
   "Greenies Original Regular Natural Dog Dental Chews, 27 oz Pack (27 Treats)",
   "Greenies Original Regular Size Dog Dental Treats 27 oz",
   "Greenies Original Dental Chews are veterinarian-recommended treats that clean teeth down to the "
   "gum line, freshening breath and reducing tartar buildup by up to 60% with daily use, earning the "
   "VOHC seal of acceptance. Made with natural ingredients, the 27 oz pack contains 27 treats sized "
   "for dogs 25-50 lbs with added vitamins, minerals, and nutrients."),
]

try:
    # Deactivate the 2 replaced pet products
    for sku in ('PET-DOG-PUZZ-004', 'PET-DOG-PUZZ-005'):
        cur.execute("UPDATE products SET is_active=FALSE, updated_at=%s WHERE sku=%s", (NOW, sku))
        print(f'Deactivated: {sku}')

    for (num, cat, sku, retail, ws_pct, promo_ratio, stock, name, folder, desc) in PRODUCTS:
        cur.execute('''
            INSERT INTO products (product_id,product_number,product_name,sku,description,
                                  category_id,currency_code,stock_quantity,is_active,is_synthetic,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,'USD',%s,TRUE,FALSE,%s,%s)
            ON CONFLICT (sku) DO UPDATE
              SET product_name=EXCLUDED.product_name, description=EXCLUDED.description,
                  stock_quantity=EXCLUDED.stock_quantity, updated_at=EXCLUDED.updated_at
            RETURNING product_id
        ''', (str(uuid.uuid4()), num, name, sku, desc, CAT[cat], stock, NOW, NOW))
        pid = cur.fetchone()[0]

        cur.execute('DELETE FROM product_image WHERE product_id=%s', (pid,))
        cur.execute('DELETE FROM product_pricing WHERE product_id=%s', (pid,))

        folder_enc = quote(folder, safe='')
        for sort in range(1, 6):
            cur.execute('''INSERT INTO product_image
                (product_image_id,product_id,image_url,sort_order,alt_text,created_at)
                VALUES (%s,%s,%s,%s,%s,%s)''',
                (str(uuid.uuid4()), pid,
                 f'image/{cat}/{folder_enc}/image_{sort}.jpg',
                 sort, f'{name[:80]} - image {sort}', NOW))

        ws    = round(retail * (1 - ws_pct), 2)
        promo = round(retail - (retail - ws) * promo_ratio, 2)
        for ptype, pval in [('Retail', retail), ('Promo', promo), ('Wholesale', ws)]:
            cur.execute('''INSERT INTO product_pricing
                (product_pricing_id,product_id,price_type,price_value,currency_code,is_synthetic,created_at,updated_at)
                VALUES (%s,%s,%s,%s,'USD',FALSE,%s,%s)''',
                (str(uuid.uuid4()), pid, ptype, pval, NOW, NOW))

        print(f'  {sku:25s}  ${retail:.2f} / ${promo:.2f} / ${ws:.2f}')

    conn.commit()
    print('\nAll 14 products committed successfully.')
except Exception as e:
    conn.rollback()
    print(f'ROLLBACK: {e}')
    import traceback; traceback.print_exc()
finally:
    conn.close()
