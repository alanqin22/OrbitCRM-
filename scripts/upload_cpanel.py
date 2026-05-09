"""
Upload all images in the local image/ folder to cPanel via UAPI,
preserving the full subfolder structure.
"""

import requests
import os
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────
CPANEL_HOST  = "https://hemera.canspace.ca:2083"
CPANEL_USER  = "agentorc"
CPANEL_TOKEN = "RX6KP38KFKTSYG3C9636MPDXBNV93ZAD"
REMOTE_BASE  = "/home2/agentorc/public_html/image"
LOCAL_BASE   = r"D:\a\crm_agent\image"

HEADERS = {"Authorization": f"cpanel {CPANEL_USER}:{CPANEL_TOKEN}"}

# ── Helpers ───────────────────────────────────────────────────────────────────

API_V2_URL = f"{CPANEL_HOST}/json-api/cpanel"

def api_v2(module, func, data=None, files=None):
    """Call cPanel API v2."""
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
        return {"cpanelresult": {"event": {"result": 0}, "data": [], "error": str(e)}}


def api_v2_ok(result) -> bool:
    return result.get("cpanelresult", {}).get("event", {}).get("result", 0) == 1


def mkdir_remote(remote_path: str) -> bool:
    """Create a remote directory via API v2 (ignore already-exists)."""
    parent = remote_path.rsplit('/', 1)[0]
    name   = remote_path.rsplit('/', 1)[1]
    result = api_v2("Fileman", "mkdir", data={"path": parent, "name": name})
    if api_v2_ok(result):
        return True
    err = str(result.get("cpanelresult", {}).get("error", ""))
    if "exist" in err.lower():
        return True
    print(f"    [mkdir error] {remote_path}: {err}")
    return False


def upload_file(local_path: str, remote_dir: str) -> bool:
    """Upload a single file to a remote directory via API v2 (overwrites existing)."""
    filename = os.path.basename(local_path)
    with open(local_path, "rb") as f:
        result = api_v2(
            "Fileman", "uploadfiles",
            data={"dir": remote_dir, "overwrite": 1},
            files={"file-1": (filename, f, "application/octet-stream")},
        )
    cr = result.get("cpanelresult", {})
    data = cr.get("data", [{}])
    if data and data[0].get("succeeded", 0) == 1:
        return True
    # Check per-file status
    uploads = data[0].get("uploads", []) if data else []
    if uploads and uploads[0].get("status") == 1:
        return True
    reason = uploads[0].get("reason", "") if uploads else ""
    if "already exists" in reason.lower():
        return True   # treat as success
    err = cr.get("error") or reason or result
    print(f"    [upload error] {filename}: {err}")
    return False


def list_remote_files(remote_dir: str) -> dict:
    """Return dict {filename: size_bytes} for files in a remote directory.
    Files with size 0 are included so the caller can force re-upload them."""
    result = api_v2("Fileman", "listfiles",
                    data={"dir": remote_dir, "include_mime": 0})
    entries = result.get("cpanelresult", {}).get("data", [])
    def _sz(e):
        try: return int(e.get("size") or 0)
        except (ValueError, TypeError): return 0
    return {e["file"]: _sz(e) for e in entries if e.get("type") == "file"}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Collect all image files and the unique dirs we need to create
    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    all_files   = []   # list of (local_path, remote_dir)
    remote_dirs = []   # ordered list of dirs to create

    for root, dirs, files in os.walk(LOCAL_BASE):
        dirs.sort()   # consistent order
        rel = os.path.relpath(root, LOCAL_BASE).replace("\\", "/")
        remote_dir = REMOTE_BASE if rel == "." else f"{REMOTE_BASE}/{rel}"

        if rel != ".":
            remote_dirs.append(remote_dir)

        for fname in sorted(files):
            if os.path.splitext(fname)[1].lower() in image_exts:
                all_files.append((os.path.join(root, fname), remote_dir))

    print(f"Dirs to create : {len(remote_dirs)}")
    print(f"Files to upload: {len(all_files)}")
    print()

    # ── Step 1: create all remote directories ────────────────────────────────
    print("Creating remote directories...")
    for d in remote_dirs:
        ok = mkdir_remote(d)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {d}")
    print()

    # ── Step 2: upload files (skip already-present ones) ─────────────────────
    print("Uploading images...")

    # Pre-fetch list of existing files per remote dir to skip re-uploads
    print("  Checking existing remote files...")
    existing_per_dir: dict[str, dict] = {}
    unique_dirs = {rd for _, rd in all_files}
    for rd in sorted(unique_dirs):
        existing_per_dir[rd] = list_remote_files(rd)

    already_present = sum(
        1 for lp, rd in all_files
        if existing_per_dir.get(rd, {}).get(os.path.basename(lp), 0) > 0
    )
    zero_byte = sum(
        1 for lp, rd in all_files
        if os.path.basename(lp) in existing_per_dir.get(rd, {})
        and existing_per_dir[rd][os.path.basename(lp)] == 0
    )
    print(f"  {already_present} files OK on server, {zero_byte} zero-byte (will re-upload), "
          f"{len(all_files)-already_present-zero_byte} missing.\n")

    success = 0
    skipped = 0
    failed  = []

    for i, (local_path, remote_dir) in enumerate(all_files, 1):
        fname = os.path.basename(local_path)
        rel_display = local_path.replace(LOCAL_BASE, "").lstrip("\\/")
        remote_size = existing_per_dir.get(remote_dir, {}).get(fname, -1)
        if remote_size > 0:
            # File exists and has content — skip
            skipped += 1
            print(f"  [{i:3}/{len(all_files)}] [SKIP] {rel_display}")
            continue
        tag_prefix = "REUP" if remote_size == 0 else "NEW "  # 0 = zero-byte, -1 = missing
        ok = upload_file(local_path, remote_dir)
        tag = "OK" if ok else "FAIL"
        print(f"  [{i:3}/{len(all_files)}] [{tag}/{tag_prefix}] {rel_display}")
        if ok:
            success += 1
            existing_per_dir.setdefault(remote_dir, {})[fname] = os.path.getsize(local_path)
        else:
            failed.append((local_path, remote_dir))
        # small pause every 20 uploads
        if (success + len(failed)) % 20 == 0:
            time.sleep(1)

    # ── Step 3: retry failures once ──────────────────────────────────────────
    if failed:
        print(f"\nRetrying {len(failed)} failed uploads...")
        time.sleep(5)
        still_failed = []
        for local_path, remote_dir in failed:
            ok = upload_file(local_path, remote_dir)
            rel_display = local_path.replace(LOCAL_BASE, "").lstrip("\\/")
            tag = "OK" if ok else "FAIL"
            print(f"  [retry][{tag}] {rel_display}")
            if ok:
                success += 1
            else:
                still_failed.append(local_path)

        if still_failed:
            print(f"\nPermanently failed ({len(still_failed)}):")
            for p in still_failed:
                print(f"  {p}")

    print(f"\nDone. {skipped} skipped (already present), {success} newly uploaded, {len(failed)} failed.")
    print(f"Total on server: {skipped + success}/{len(all_files)}")


if __name__ == "__main__":
    main()
