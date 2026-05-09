"""
Fix: re-upload 30 new Electronics product images to correctly-named
remote directories (with spaces, not percent-encoded literal names).

Root cause: add_30_electronics.py passed URL-encoded folder names
(e.g. "Apple%20iPhone%2015%20Pro...") to the cPanel mkdir API,
creating directories with literal '%' characters in their names.
Apache decodes %20 → space when serving requests, so the directories
were never found → 404 → images showed as letter avatars.

This script:
  1. Reads actual folder names from the local filesystem (spaces intact).
  2. Creates remote directories using unencoded names (spaces).
  3. Uploads all images to those correctly-named remote directories.

The product_image URLs in the DB stay unchanged — they are already
correct: https://agentorc.ca/image/Electronics/<folder%20encoded>/image_N.jpg
Apache maps those decoded URLs → the space-named directories.
"""

import os, sys, time, requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────
LOCAL_ELEC  = r"D:\a\crm_agent\image\Electronics"
REMOTE_BASE = "/home2/agentorc/public_html/image"
REMOTE_ELEC = f"{REMOTE_BASE}/Electronics"

CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
HEADERS      = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}
API_URL      = f"{CPANEL_HOST}/json-api/cpanel"

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# These are the 30 new product folder names exactly as they exist on disk
# (i.e., with spaces — NOT URL-encoded).
NEW_PRODUCT_FOLDERS = [
    "Apple iPhone 15 Pro 256GB Natural Titanium",
    "Samsung Galaxy S24 Ultra 256GB Titanium Black",
    "Apple iPad Pro 11-inch M4 256GB Wi-Fi",
    "Samsung 65 Inch Crystal UHD 4K Smart TV CU8000",
    "Sony WH-1000XM5 Wireless Noise Canceling Headphones",
    "Bose QuietComfort Ultra Wireless Headphones",
    "Nintendo Switch OLED Model White",
    "Sony PlayStation 5 Slim Disc Edition",
    "Microsoft Xbox Series X 1TB Gaming Console",
    "Apple Watch Series 10 GPS 46mm Jet Black",
    "Google Pixel 9 Pro 256GB Obsidian",
    "DJI Mini 4 Pro Drone Fly More Combo",
    "GoPro HERO13 Black Action Camera",
    "Canon EOS R50 Mirrorless Camera with 18-45mm Lens",
    "Apple MacBook Air 13 inch M3 Midnight",
    "ASUS ROG Strix G16 Gaming Laptop Core i9 RTX 4070",
    "Razer DeathAdder V3 HyperSpeed Wireless Mouse",
    "Razer BlackWidow V4 Mechanical Gaming Keyboard",
    "Sony DualSense Wireless Controller Midnight Black",
    "ASUS RT-AX86U WiFi 6 Gaming Router AX5700",
    "Amazon Fire TV Stick 4K Max 2nd Gen",
    "Anker 737 Power Bank 24000mAh 140W",
    "Samsung 55 inch QN90D Neo QLED 4K TV",
    "JBL Charge 5 Portable Bluetooth Speaker",
    "Fitbit Charge 6 Fitness Tracker Black",
    "Garmin Vivoactive 5 GPS Smartwatch",
    "Epson EcoTank ET-2800 Wireless Inkjet All-in-One Printer",
    "Ring Video Doorbell Pro 2",
    "Philips Hue Smart Bulb Starter Kit 4-Pack White Color Ambiance",
    "WD Black SN850X 2TB NVMe M.2 SSD",
]


# ── cPanel helpers ────────────────────────────────────────────────────────────

def cpanel_call(module, func, data=None, files=None):
    params = {
        "cpanel_jsonapi_version": "2",
        "cpanel_jsonapi_module": module,
        "cpanel_jsonapi_func": func,
    }
    try:
        r = requests.post(API_URL, headers=HEADERS, params=params,
                          data=data or {}, files=files, verify=False, timeout=60)
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}


def cpanel_ok(res) -> bool:
    return res.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1


def mkdir_remote(parent: str, name: str) -> bool:
    """Create remote directory; silently succeed if it already exists."""
    res = cpanel_call("Fileman", "mkdir", data={"path": parent, "name": name})
    if cpanel_ok(res):
        return True
    err = str(res.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"    [mkdir FAIL] {parent}/{name}: {err}")
    return False


def list_remote_files(remote_dir: str) -> dict:
    """Return {filename: size} for files in remote_dir."""
    res = cpanel_call("Fileman", "listfiles", data={"dir": remote_dir, "include_mime": 0})
    entries = res.get("cpanelresult", {}).get("data", [])
    out = {}
    for e in entries:
        if e.get("type") == "file":
            try:
                out[e["file"]] = int(e.get("size") or 0)
            except (ValueError, TypeError):
                out[e["file"]] = 0
    return out


def upload_file(local_path: str, remote_dir: str) -> bool:
    filename = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        res = cpanel_call(
            "Fileman", "uploadfiles",
            data={"dir": remote_dir, "overwrite": 1},
            files={"file-1": (filename, f, "application/octet-stream")},
        )
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    total_ok = 0
    total_fail = 0
    total_skip = 0

    print(f"Re-uploading {len(NEW_PRODUCT_FOLDERS)} Electronics product folders")
    print(f"Local base : {LOCAL_ELEC}")
    print(f"Remote base: {REMOTE_ELEC}")
    print()

    for folder_name in NEW_PRODUCT_FOLDERS:
        local_prod_dir = os.path.join(LOCAL_ELEC, folder_name)

        if not os.path.isdir(local_prod_dir):
            print(f"[SKIP] Local folder not found: {folder_name}")
            continue

        img_files = sorted([
            f for f in os.listdir(local_prod_dir)
            if os.path.splitext(f)[1].lower() in IMG_EXTS
        ])
        if not img_files:
            print(f"[SKIP] No images in: {folder_name}")
            continue

        # Remote directory uses the UNENCODED folder name (with spaces).
        # Apache will URL-decode incoming requests, so
        #   GET /image/Electronics/Apple%20iPhone.../image_1.jpg
        #   → looks for dir  "Apple iPhone..."  ← correct
        remote_prod_dir = f"{REMOTE_ELEC}/{folder_name}"

        print(f"[{folder_name[:60]}]")

        # Step 1: Create remote dir with unencoded name
        ok = mkdir_remote(REMOTE_ELEC, folder_name)
        print(f"  mkdir {'OK' if ok else 'FAIL'}: {folder_name[:55]}")

        # Step 2: Check what's already there (by unencoded path)
        existing = list_remote_files(remote_prod_dir)
        already  = sum(1 for f in img_files if existing.get(f, 0) > 0)
        print(f"  {already}/{len(img_files)} already present on server")

        # Step 3: Upload missing / zero-byte files
        for img_file in img_files:
            local_path   = os.path.join(local_prod_dir, img_file)
            remote_size  = existing.get(img_file, -1)
            if remote_size > 0:
                total_skip += 1
                print(f"  [SKIP ] {img_file} ({remote_size} bytes)")
                continue
            tag = "REUP" if remote_size == 0 else "NEW "
            ok  = upload_file(local_path, remote_prod_dir)
            status = "OK  " if ok else "FAIL"
            print(f"  [{status}/{tag}] {img_file}")
            if ok:
                total_ok += 1
                time.sleep(0.3)
            else:
                total_fail += 1

        print()

    print("=" * 60)
    print(f"Done.  Uploaded: {total_ok}  Skipped: {total_skip}  Failed: {total_fail}")
    if total_fail:
        print("Re-run this script to retry failed uploads.")


if __name__ == "__main__":
    main()
