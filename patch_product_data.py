"""
patch_product_data.py — adds product_number to ProductData model in products/router.py

PROBLEM:
  ProductData model has product_id but not product_number.
  When user enters a product number (e.g. 32) in the Price History dialog,
  the HTML sends productData: {context: 'price_history_report', product_number: 32}
  but Pydantic silently drops product_number (not in model) →
  pre_router gets empty productData → passthru → Ollama → Connection refused.

FIX:
  Add product_number: Optional[int] = None to ProductData model.

Run:
  cd D:\\a\\crm_agent
  python patch_product_data.py
"""

from pathlib import Path

TARGET = Path(r"D:\a\crm_agent\app\agents\products\router.py")

OLD = "    product_id:      Optional[str]   = None"
NEW = ("    product_id:      Optional[str]   = None\n"
       "    product_number:  Optional[int]   = None   # for price history by number")

def patch():
    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found"); raise SystemExit(1)
    src = TARGET.read_text(encoding="utf-8")
    if "product_number" in src:
        print("ALREADY PATCHED — product_number already in ProductData."); return
    if OLD not in src:
        print("ERROR: anchor not found — check file manually."); raise SystemExit(1)
    src = src.replace(OLD, NEW, 1)
    TARGET.write_text(src, encoding="utf-8")
    print("PATCHED: product_number added to ProductData model")
    print("\ngit add app/agents/products/router.py")
    print('git commit -m "fix: add product_number to ProductData for price history"')
    print("git push")

if __name__ == "__main__":
    patch()
