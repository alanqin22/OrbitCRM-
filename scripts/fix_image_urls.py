"""
Fix product_image URLs in Railway DB:
  relative  →  image/Electronics/foo/image_1.jpg
  absolute  →  https://agentorc.ca/image/Electronics/foo/image_1.jpg

Run once, safe to re-run (skips rows already using the absolute URL).
"""

import psycopg2

DB_URL  = "postgresql://postgres:SimKpntYtoGdLWdVsXglunQqHZMHXUfQ@shinkansen.proxy.rlwy.net:26832/railway"
BASE_URL = "https://agentorc.ca/"   # trailing slash — relative paths start with 'image/'

def main():
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Count how many rows need fixing
    cur.execute("""
        SELECT COUNT(*) FROM product_image
        WHERE image_url LIKE 'image/%'
          AND image_url NOT LIKE 'http%'
    """)
    total = cur.fetchone()[0]
    print(f"Rows to fix: {total}")

    if total == 0:
        print("Nothing to do — all URLs already absolute.")
        conn.close()
        return

    # Preview first 10
    cur.execute("""
        SELECT product_image_id, image_url
        FROM product_image
        WHERE image_url LIKE 'image/%'
          AND image_url NOT LIKE 'http%'
        ORDER BY image_url
        LIMIT 10
    """)
    print("\nSample rows (before):")
    for row in cur.fetchall():
        print(f"  {row[0]}  ->  {row[1]}")

    confirm = input(f"\nUpdate all {total} rows? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("Aborted.")
        conn.close()
        return

    # Bulk update: prepend base URL to every relative path
    cur.execute("""
        UPDATE product_image
        SET image_url = %s || image_url
        WHERE image_url LIKE 'image/%%'
          AND image_url NOT LIKE 'http%%'
    """, (BASE_URL,))

    updated = cur.rowcount
    conn.commit()
    print(f"\nDone — {updated} rows updated.")

    # Verify
    cur.execute("""
        SELECT COUNT(*) FROM product_image
        WHERE image_url LIKE 'image/%'
          AND image_url NOT LIKE 'http%'
    """)
    remaining = cur.fetchone()[0]
    print(f"Remaining relative URLs: {remaining}")

    # Show a couple of fixed rows
    cur.execute("""
        SELECT image_url FROM product_image
        WHERE image_url LIKE %s
        LIMIT 5
    """, (BASE_URL + 'image/%',))
    print("\nSample rows (after):")
    for row in cur.fetchall():
        print(f"  {row[0]}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
