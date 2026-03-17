"""
patch_web_files.py — fixes two minor UI issues in web HTML files.

FIX 1 — contact-chat.html sparkline font:
  .metric-sparkline and .sparkline-cell use font-family: monospace which
  maps to "Courier New" on Windows — does not include block chars (▁ U+2581).
  Fix: add 'Segoe UI Symbol' (Windows) and 'Noto Sans Symbols' (Linux/Mac)
  to the font stack so ▁ ▂ ▃ etc. render correctly.

FIX 2 — product-chat.html price history message flag:
  _directQuery sends message:'product_direct_operation' which the pre_router
  handles via the productData.context path. This is correct and works when
  the backend has product_number in the ProductData model (already patched).
  No HTML change needed for price history — backend fix is sufficient.

Run:
  cd D:\\a\\crm_agent
  python patch_web_files.py
"""

from pathlib import Path

WEB = Path(r"D:\a\crm_agent\web")

CONTACT_HTML = WEB / "contact-chat.html"

# ── Fix 1a: .metric-sparkline font ───────────────────────────────────────────
OLD_METRIC_FONT = """\
        .metric-sparkline {
            font-family: monospace;"""

NEW_METRIC_FONT = """\
        .metric-sparkline {
            font-family: 'Segoe UI Symbol', 'Noto Sans Symbols', 'Apple Symbols', monospace;"""

# ── Fix 1b: .sparkline-cell font ─────────────────────────────────────────────
OLD_CELL_FONT = """\
        .summary-table .sparkline-cell {
            font-family: monospace;"""

NEW_CELL_FONT = """\
        .summary-table .sparkline-cell {
            font-family: 'Segoe UI Symbol', 'Noto Sans Symbols', 'Apple Symbols', monospace;"""


def patch_contact():
    if not CONTACT_HTML.exists():
        print(f"  SKIP (missing): {CONTACT_HTML}"); return

    src = original = CONTACT_HTML.read_text(encoding="utf-8")

    if "Segoe UI Symbol" in src:
        print("  ALREADY DONE : contact-chat.html sparkline font"); return

    for old, new, label in [
        (OLD_METRIC_FONT, NEW_METRIC_FONT, ".metric-sparkline font"),
        (OLD_CELL_FONT,   NEW_CELL_FONT,   ".sparkline-cell font"),
    ]:
        if old in src:
            src = src.replace(old, new, 1)
            print(f"  ✓ {label}")
        else:
            print(f"  - SKIP (anchor not found): {label}")

    if src != original:
        CONTACT_HTML.write_text(src, encoding="utf-8")
        print(f"  PATCHED: contact-chat.html")
    else:
        print("  NO CHANGES in contact-chat.html")


if __name__ == "__main__":
    print(f"Web dir: {WEB}\n")
    patch_contact()
    print("\nCommit and push:")
    print("  git add web/contact-chat.html")
    print('  git commit -m "fix: sparkline font includes block chars (Segoe UI Symbol)"')
    print("  git push")
    print("\nThe ▁ characters should now render correctly in Chrome/Edge/Firefox on Windows.")
    print("Note: product-chat.html price history fix was already applied via backend patch.")
