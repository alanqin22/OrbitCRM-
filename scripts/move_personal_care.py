"""
Move Dove and H&S images from Personal Care to Health & Wellness on cPanel,
then update the database:
  - Dove + H&S → Health & Wellness category, fix image URLs
  - Other 15 Personal Care products → Office Supplies category, fix relative URLs
  - Deactivate Personal Care category
"""

import os
import time
import requests
import psycopg2
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
REMOTE_BASE  = "/home2/agentorc/public_html/image"
LOCAL_BASE   = r"D:\a\crm_agent\image"

HEADERS = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}
API_V2_URL = f"{CPANEL_HOST}/json-api/cpanel"

DB_DSN = "postgresql://postgres:aria@localhost:5434/crmdb"

HEALTH_CAT_ID    = "fcaaec3d-21d4-461d-9dbe-849c7c14c7de"
OFFICE_CAT_ID    = "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec"
PERSONAL_CAT_ID  = "adf36cbb-9243-4a60-96ac-f5998361ed91"

DOVE_ID  = "b0f03d97-7018-49db-84cf-06d855e947c2"
HS_ID    = "ac4ac2b1-a3e6-41e2-922f-63fa599e97f9"

DOVE_FOLDER = "Dove Men+Care Body Wash Extra Fresh 30 fl oz"
HS_FOLDER   = "Head and Shoulders Classic Clean Dandruff Shampoo 32.1 fl oz"


# ── cPanel helpers ─────────────────────────────────────────────────────────────

def api_v2(module, func, data=None, files=None):
    params = {
        "cpanel_jsonapi_version": "2",
        "cpanel_jsonapi_module": module,
        "cpanel_jsonapi_func": func,
    }
    try:
        r = requests.post(API_V2_URL, headers=HEADERS, params=params,
                          data=data or {}, files=files, verify=False, timeout=60)
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}

def api_v2_ok(result):
    return result.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1

def mkdir_remote(remote_path):
    parent = remote_path.rsplit('/', 1)[0]
    name   = remote_path.rsplit('/', 1)[1]
    result = api_v2("Fileman", "mkdir", data={"path": parent, "name": name})
    if api_v2_ok(result):
        return True
    err = str(result.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"  [mkdir error] {remote_path}: {err}")
    return False

def upload_file(local_path, remote_dir):
    filename = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        result = api_v2("Fileman", "uploadfiles",
                        data={"dir": remote_dir, "overwrite": 1},
                        files={"file-1": (filename, f, "application/octet-stream")})
    cr = result.get("cpanelresult", {})
    data = cr.get("data", [{}])
    uploads = data[0].get("uploads", []) if data else []
    if data and data[0].get("succeeded", 0) == 1:
        return True
    if uploads and uploads[0].get("status") == 1:
        return True
    reason = uploads[0].get("reason", "") if uploads else ""
    if "already exists" in reason.lower():
        return True
    err = cr.get("error") or reason or result
    print(f"  [upload error] {filename}: {err}")
    return False


def upload_folder(category_name, folder_name):
    """Upload all images in image/<category>/<folder> to remote."""
    local_dir   = os.path.join(LOCAL_BASE, category_name, folder_name)
    remote_cat  = f"{REMOTE_BASE}/{category_name}"
    remote_dir  = f"{remote_cat}/{folder_name}"

    print(f"\nUploading: {category_name}/{folder_name}")
    print(f"  Creating remote dir: {remote_dir}")
    mkdir_remote(remote_cat)
    mkdir_remote(remote_dir)

    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = [f for f in os.listdir(local_dir)
             if os.path.splitext(f)[1].lower() in image_exts]
    files.sort()

    for fname in files:
        local_path = os.path.join(local_dir, fname)
        ok = upload_file(local_path, remote_dir)
        print(f"  [{'OK' if ok else 'FAIL'}] {fname}")
        time.sleep(0.3)


# ── DB updates ─────────────────────────────────────────────────────────────────

def run_db_updates():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()

    print("\n=== Database Updates ===")

    # 1. Update Dove + H&S → Health & Wellness category
    cur.execute(
        "UPDATE products SET category_id = %s WHERE product_id IN (%s, %s)",
        (HEALTH_CAT_ID, DOVE_ID, HS_ID)
    )
    print(f"  Updated {cur.rowcount} products to Health & Wellness (Dove + H&S)")

    OLD_PREFIX = "https://agentorc.ca/image/Personal%20Care/"
    NEW_PREFIX = "https://agentorc.ca/image/Health%20%26%20Wellness/"

    # 2. Update image URLs for Dove: Personal Care → Health & Wellness
    cur.execute(
        "UPDATE product_image SET image_url = REPLACE(image_url, %s, %s) WHERE product_id = %s",
        (OLD_PREFIX, NEW_PREFIX, DOVE_ID)
    )
    print(f"  Fixed Dove image URLs: {cur.rowcount} rows")

    # 3. Update image URLs for H&S: Personal Care → Health & Wellness
    cur.execute(
        "UPDATE product_image SET image_url = REPLACE(image_url, %s, %s) WHERE product_id = %s",
        (OLD_PREFIX, NEW_PREFIX, HS_ID)
    )
    print(f"  Fixed H&S image URLs: {cur.rowcount} rows")

    # 4. Update remaining 15 Personal Care products → Office Supplies
    cur.execute(
        """UPDATE products SET category_id = %s
           WHERE category_id = %s
             AND product_id NOT IN (%s, %s)""",
        (OFFICE_CAT_ID, PERSONAL_CAT_ID, DOVE_ID, HS_ID)
    )
    print(f"  Updated {cur.rowcount} products to Office Supplies")

    # 5. Fix relative image URLs for those 15 products (add https://agentorc.ca/ prefix)
    cur.execute(
        """UPDATE product_image
           SET image_url = 'https://agentorc.ca/' || image_url
           WHERE product_id IN (
               SELECT product_id FROM products WHERE category_id = %s
           )
           AND image_url NOT LIKE 'http%%' """,
        (OFFICE_CAT_ID,)
    )
    print(f"  Fixed relative image URLs: {cur.rowcount} rows")

    # 6. Deactivate Personal Care category
    cur.execute(
        "UPDATE category SET is_active = false WHERE category_id = %s",
        (PERSONAL_CAT_ID,)
    )
    print(f"  Deactivated Personal Care category: {cur.rowcount} rows")

    conn.commit()
    cur.close()
    conn.close()
    print("  DB commit OK")


if __name__ == "__main__":
    print("Step 1: Upload Dove images to Health & Wellness on cPanel...")
    upload_folder("Health & Wellness", DOVE_FOLDER)

    print("\nStep 2: Upload Head & Shoulders images to Health & Wellness on cPanel...")
    upload_folder("Health & Wellness", HS_FOLDER)

    print("\nStep 3: Run database updates...")
    run_db_updates()

    print("\nDone!")
