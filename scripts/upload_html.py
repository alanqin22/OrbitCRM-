import requests, urllib3, os
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HOST    = "https://hemera.canspace.ca:2083"
USER    = "agentorc"
TOKEN   = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
HEADERS = {"Authorization": f"cpanel {USER}:{TOKEN}"}
API     = f"{HOST}/json-api/cpanel"
REMOTE  = "/home2/agentorc/public_html"

def upload(local_path, remote_dir):
    fname = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        r = requests.post(API, headers=HEADERS,
            params={"cpanel_jsonapi_version":"2",
                    "cpanel_jsonapi_module":"Fileman",
                    "cpanel_jsonapi_func":"uploadfiles"},
            data={"dir": remote_dir, "overwrite": 1},
            files={"file-1": (fname, f, "text/html")},
            verify=False, timeout=60)
    result = r.json().get("cpanelresult", {})
    data = result.get("data", [{}])
    if data and data[0].get("succeeded", 0) == 1:
        return True
    uploads = data[0].get("uploads", []) if data else []
    return bool(uploads and uploads[0].get("status") == 1)

for fname in ["product-chat.html", "store-home.html"]:
    local = os.path.join(r"D:\a\crm_agent", fname)
    ok = upload(local, REMOTE)
    print(f"{fname}: {'OK' if ok else 'FAIL'}")
