"""
patch_accounting_router.py — fixes accounting/router.py hand-built chat_input dict.

PROBLEM:
  accounting/router.py builds chat_input as a manual dict that omits
  'routerAction' and 'mode', so the pre_router short-circuit never fires
  and the request falls through to Ollama → Connection refused on Railway.

FIXES:
  1. Add "routerAction": ci.routerAction and "mode": ci.mode to the dict
  2. Fix ci.message[:100] NoneType crash (message is now Optional)
  3. Fix "user_input": ci.message → ci.message or ""

Run from PowerShell:
  cd D:\\a\\crm_agent
  python patch_accounting_router.py
"""

from pathlib import Path

TARGET = Path(r"D:\a\crm_agent\app\agents\accounting\router.py")

# The line we anchor on — last field in the hand-built dict before the closing brace
OLD = '        "endDate":     ci.endDate,\n    }'

NEW = '        "endDate":     ci.endDate,\n        # ── Routing control (must be forwarded so pre_router short-circuit fires) ──\n        "mode":         ci.mode,\n        "routerAction": ci.routerAction,\n    }'

# Also fix the None crash on ci.message[:100]
OLD2 = 'ci.message[:100]'
NEW2 = '(ci.message or "")[:100]'

# Fix user_input None
OLD3 = '"user_input":      ci.message,'
NEW3 = '"user_input":      ci.message or "",'

# Fix message in dict
OLD4 = '        "message":    ci.message,'
NEW4 = '        "message":    ci.message or "",'


def patch():
    if not TARGET.exists():
        print(f"ERROR: File not found: {TARGET}")
        raise SystemExit(1)

    src = original = TARGET.read_text(encoding="utf-8")

    if "routerAction" in src and "ci.routerAction" in src:
        print("ALREADY PATCHED — routerAction already in dict.")
        return

    replacements = [
        (OLD,  NEW,  "Add mode+routerAction to hand-built dict"),
        (OLD2, NEW2, "Fix ci.message[:100] NoneType crash"),
        (OLD3, NEW3, "Fix user_input None"),
        (OLD4, NEW4, "Fix message None in dict"),
    ]

    for old, new, label in replacements:
        if old in src:
            src = src.replace(old, new, 1)
            print(f"  ✓ {label}")
        else:
            print(f"  - SKIP (not found): {label}")

    if src == original:
        print("NO CHANGES MADE — check anchor strings above.")
        return

    TARGET.write_text(src, encoding="utf-8")
    print(f"\nPatched: {TARGET}")
    print("\nCommit and push:")
    print("  git add app/agents/accounting/router.py")
    print('  git commit -m "fix: add mode+routerAction to accounting chat_input dict"')
    print("  git push")
    print("\nVerify:")
    print('  Invoke-RestMethod -Uri "https://orbitcrm-production.up.railway.app/accounting-chat" `')
    print('    -Method POST -ContentType "application/json" `')
    print('    -Body \'{"chatInput": {"mode": "list_invoices", "routerAction": true}, "sessionId": "smoke"}\'')


if __name__ == "__main__":
    patch()
