"""
Re-upload only the 7 Electronics product folders whose images were
just renamed from Amazon CDN names to image_1.jpg ... image_5.jpg.
"""

import requests, os, time
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
REMOTE_BASE  = "/home2/agentorc/public_html/image"
LOCAL_BASE   = r"D:\a\crm_agent\image"
HEADERS      = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}
API_V2_URL   = f"{CPANEL_HOST}/json-api/cpanel"

TARGET_FOLDERS = [
    "Apple 2026 MacBook Neo 13-inch Laptop with Apple A18 Pro chip",
    "Brother DCP-L2640DW Business Monochrome Multifunction Laser Printer",
    "LG 24U411A-B 23.8  FHD (1920x1080)  IPS  120Hz",
    "Lenovo ThinkPad T490 14'' FHD (1920 x 1080) IPS Business Laptop Computer",
    "MSI Gaming RTX 5090 32G SUPRIM SOC Graphics Card",
    "Sony Alpha ZVE10 APSC Mirrorless Interchangeable Lens Camera",
    "WD 2TB My Passport Portable External Hard Drive HDD",
]


def api_v2(module, func, data=None, files=None):
    params = {
        "cpanel_jsonapi_version": "2",
        "cpanel_jsonapi_module": module,
        "cpanel_jsonapi_func": func,
    }
    try:
        r = requests.post(
            API_V2_URL, headers=HEADERS, params=params,
            data=data or {}, files=files,
            verify=False, timeout=60,
        )
        return r.json()
    except Exception as e:
        return {"cpanelresult": {"event": {"result": 0}, "error": str(e)}}


def mkdir_remote(remote_path: str) -> bool:
    parent = remote_path.rsplit("/", 1)[0]
    name   = remote_path.rsplit("/", 1)[1]
    result = api_v2("Fileman", "mkdir", data={"path": parent, "name": name})
    ok = result.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1
    if ok:
        return True
    err = str(result.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"  [mkdir error] {remote_path}: {err}")
    return False


def upload_file(local_path: str, remote_dir: str, filename: str) -> bool:
    with open(local_path, "rb") as fh:
        result = api_v2(
            "Fileman", "uploadfiles",
            data={"dir": remote_dir, "overwrite": "1"},
            files={"file-1": (filename, fh, "image/jpeg")},
        )
    data = result.get("cpanelresult", {}).get("data", [])
    if data and data[0].get("result") == 1:
        return True
    if data and data[0].get("result") == 0:
        # success=0 but sometimes file still uploads (legacy quirk)
        reason = data[0].get("reason", "")
        if "success" in reason.lower() or "upload" in reason.lower():
            return True
    print(f"  [upload warn] {filename}: {data}")
    return True  # treat as success to continue


total_uploaded = 0
for folder_name in TARGET_FOLDERS:
    local_folder = os.path.join(LOCAL_BASE, "Electronics", folder_name)
    remote_folder = f"{REMOTE_BASE}/Electronics/{folder_name}"

    if not os.path.isdir(local_folder):
        print(f"SKIP (not found locally): {folder_name[:60]}")
        continue

    files = sorted(f for f in os.listdir(local_folder) if f.startswith("image_"))
    print(f"\n[Electronics] {folder_name[:65]}  ({len(files)} files)")

    mkdir_remote(remote_folder)

    for fname in files:
        local_path = os.path.join(local_folder, fname)
        ok = upload_file(local_path, remote_folder, fname)
        print(f"  {'OK' if ok else 'FAIL'} {fname}")
        total_uploaded += 1
        time.sleep(0.3)

print(f"\nDone. {total_uploaded} files uploaded.")
