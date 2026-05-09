"""
Move 9 Personal Care image folders to Health & Wellness,
upload them to cPanel, and update the database.
"""
import os, shutil, time, requests, psycopg2, urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOCAL_BASE   = r"D:\a\crm_agent\image"
CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
REMOTE_BASE  = "/home2/agentorc/public_html/image"
HEADERS      = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}
API_V2_URL   = f"{CPANEL_HOST}/json-api/cpanel"

DB_DSN           = "postgresql://postgres:aria@localhost:5434/crmdb"
HEALTH_CAT_ID    = "fcaaec3d-21d4-461d-9dbe-849c7c14c7de"
OFFICE_CAT_ID    = "cdcbd1da-11a2-497a-bc1c-99ff2cd440ec"

PRODUCT_IDS = [
    "d6c22324-a493-4bc2-a165-aba7941fdccf",  # Bearback
    "61166dfa-7ce7-4e2e-a324-0adae0310696",  # Brickell
    "2b4b127a-a0f7-4332-9616-99e6dfb73b24",  # Brightup
    "c5f5857a-75a8-445b-8182-ad2a8d0331bd",  # Bushbalm
    "960fb8bf-c8f8-4031-89a0-02566e9b1eed",  # Crest
    "d39207d9-7c98-48fa-835e-13102bbf2483",  # Fresh BALLS
    "0236eee0-c50f-4554-90f4-ab6124a3249c",  # Japanese Nail Clippers
    "24e3b771-5e3f-4800-ae1e-8bd4ee65c57d",  # MERIDIAN
    "e365e384-7eaf-444f-8d71-dfaf49c42087",  # OLOV
]


# ── cPanel helpers ─────────────────────────────────────────────────────────────

def api_v2(module, func, data=None, files=None):
    params = {"cpanel_jsonapi_version": "2",
              "cpanel_jsonapi_module": module,
              "cpanel_jsonapi_func": func}
    try:
        r = requests.post(API_V2_URL, headers=HEADERS, params=params,
                          data=data or {}, files=files, verify=False, timeout=60)
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}

def api_v2_ok(result):
    return result.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1

def mkdir_remote(remote_path):
    parent = remote_path.rsplit("/", 1)[0]
    name   = remote_path.rsplit("/", 1)[1]
    result = api_v2("Fileman", "mkdir", data={"path": parent, "name": name})
    if api_v2_ok(result):
        return True
    err = str(result.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"  [mkdir error] {remote_path}: {err}")
    return False

def upload_file(local_path, remote_dir):
    fname = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        result = api_v2("Fileman", "uploadfiles",
                        data={"dir": remote_dir, "overwrite": 1},
                        files={"file-1": (fname, f, "application/octet-stream")})
    cr = result.get("cpanelresult", {})
    data = cr.get("data", [{}])
    if data and data[0].get("succeeded", 0) == 1:
        return True
    uploads = data[0].get("uploads", []) if data else []
    if uploads and uploads[0].get("status") == 1:
        return True
    reason = uploads[0].get("reason", "") if uploads else ""
    if "already exists" in reason.lower():
        return True
    err = cr.get("error") or reason or result
    print(f"  [upload error] {fname}: {err}")
    return False


# ── Step 1: move local folders ─────────────────────────────────────────────────

def move_local_folders():
    src_base = os.path.join(LOCAL_BASE, "Personal Care")
    dst_base = os.path.join(LOCAL_BASE, "Health & Wellness")
    folders  = os.listdir(src_base)
    print(f"\nFound {len(folders)} folders in Personal Care")
    moved = []
    for folder in folders:
        src = os.path.join(src_base, folder)
        dst = os.path.join(dst_base, folder)
        shutil.move(src, dst)
        print(f"  Moved: {folder[:70]}")
        moved.append(folder)
    return moved


# ── Step 2: upload to cPanel ───────────────────────────────────────────────────

def upload_folders(folders):
    dst_base_local  = os.path.join(LOCAL_BASE, "Health & Wellness")
    remote_cat      = f"{REMOTE_BASE}/Health & Wellness"
    image_exts      = {".jpg", ".jpeg", ".png", ".webp"}

    for folder in folders:
        local_dir  = os.path.join(dst_base_local, folder)
        remote_dir = f"{remote_cat}/{folder}"
        print(f"\n  Uploading: {folder[:60]}...")
        mkdir_remote(remote_dir)
        files = sorted(f for f in os.listdir(local_dir)
                       if os.path.splitext(f)[1].lower() in image_exts)
        for fname in files:
            ok = upload_file(os.path.join(local_dir, fname), remote_dir)
            print(f"    [{'OK' if ok else 'FAIL'}] {fname}")
            time.sleep(0.2)


# ── Step 3: DB updates ─────────────────────────────────────────────────────────

def run_db_updates():
    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur  = conn.cursor()

    ids_tuple = tuple(PRODUCT_IDS)
    placeholders = ",".join(["%s"] * len(ids_tuple))

    # Update category
    cur.execute(
        f"UPDATE products SET category_id = %s WHERE product_id IN ({placeholders})",
        (HEALTH_CAT_ID, *ids_tuple)
    )
    print(f"\n  Category updated: {cur.rowcount} products → Health & Wellness")

    # Fix image URLs: Personal%20Care → Health%20%26%20Wellness
    OLD = "https://agentorc.ca/image/Personal%20Care/"
    NEW = "https://agentorc.ca/image/Health%20%26%20Wellness/"
    cur.execute(
        f"UPDATE product_image SET image_url = REPLACE(image_url, %s, %s) WHERE product_id IN ({placeholders})",
        (OLD, NEW, *ids_tuple)
    )
    print(f"  Image URLs fixed: {cur.rowcount} rows")

    conn.commit()
    cur.close()
    conn.close()
    print("  DB commit OK")


if __name__ == "__main__":
    print("=== Step 1: Move local image folders ===")
    moved = move_local_folders()

    print("\n=== Step 2: Upload to cPanel ===")
    upload_folders(moved)

    print("\n=== Step 3: Database updates ===")
    run_db_updates()

    print("\nDone!")
