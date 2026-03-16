"""
patch_pre_routers.py — adds routerAction short-circuit to all pre_router.py files.

ROOT CAUSE:
  When chatInput has {mode: "list", routerAction: true} but no message text,
  pre_router gets empty string, finds no pattern match, falls to PASSTHRU →
  AI Agent → tries Ollama on localhost:11434 → Connection refused on Railway.

FIX:
  Inject a short-circuit block at the top of every route_request() function.
  If chat_input contains routerAction=True and a mode value, route immediately
  without touching the message-pattern matching logic.

The injected block (right after the "Message:" logger line):

    # ── routerAction short-circuit (v3.1) ───────────────────────────────────
    # HTML direct-SP calls send routerAction=True + mode in chatInput with no
    # message text.  Detect this here before message-pattern matching so we
    # never fall through to the AI Agent (which needs Ollama / OpenAI).
    _SKIP = {'routerAction', 'message', 'sessionId', 'chatInput',
             'originalBody', 'webhookUrl', 'executionMode',
             'currentMessage', 'chatHistory'}
    if chat_input.get('routerAction') and chat_input.get('mode'):
        _params = {k: v for k, v in chat_input.items()
                   if k not in _SKIP and v is not None}
        logger.info(f'→ routerAction SHORT-CIRCUIT: mode={_params.get(\"mode\")}')
        return {'router_action': True, 'params': _params}

Run from PowerShell:
  cd D:\\a\\crm_agent
  python patch_pre_routers.py
"""

import re
from pathlib import Path

BASE = Path(r"D:\a\crm_agent\app\agents")

AGENT_DIRS = [
    "accounting", "accounts", "activities", "analytics",
    "contacts", "leads", "notifications", "opportunities",
    "orders", "products",
]

# The short-circuit block to inject — uses 4-space indent to match pre_router style
SHORT_CIRCUIT = '''
    # ── routerAction short-circuit (v3.1) ───────────────────────────────────
    # HTML direct-SP calls send routerAction=True + mode in chatInput with no
    # message text.  Detect this here before message-pattern matching so we
    # never fall through to the AI Agent (which needs Ollama / OpenAI).
    _SKIP = {'routerAction', 'message', 'sessionId', 'chatInput',
             'originalBody', 'webhookUrl', 'executionMode',
             'currentMessage', 'chatHistory'}
    if chat_input.get('routerAction') and chat_input.get('mode'):
        _params = {k: v for k, v in chat_input.items()
                   if k not in _SKIP and v is not None}
        logger.info(f'→ routerAction SHORT-CIRCUIT: mode={_params.get("mode")}')
        return {'router_action': True, 'params': _params}
'''

# Opportunities already has a body_mode check — inject BEFORE it, keyed differently
SHORT_CIRCUIT_OPP = '''
    # ── routerAction short-circuit (v3.1) ───────────────────────────────────
    _SKIP = {'routerAction', 'message', 'sessionId', 'chatInput',
             'originalBody', 'webhookUrl', 'executionMode',
             'currentMessage', 'chatHistory'}
    if chat_input.get('routerAction') and chat_input.get('mode'):
        _params = {k: v for k, v in chat_input.items()
                   if k not in _SKIP and v is not None}
        logger.info(f'→ routerAction SHORT-CIRCUIT: mode={_params.get("mode")}')
        return {'router_action': True, 'params': _params}
'''


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def write(p: Path, src: str) -> None:
    p.write_text(src, encoding="utf-8")

def already_patched(src: str) -> bool:
    return "routerAction SHORT-CIRCUIT" in src

def patch_message_style(src: str) -> str:
    """
    Agents: accounting, accounts, contacts, products
    Inject after the first "logger.info(f'Message:" line inside route_request.
    """
    # Match the Message logger line and inject after it
    pattern = r"(    logger\.info\(f'Message:[^\n]*\n)"
    match = re.search(pattern, src)
    if not match:
        return src
    insert_pos = match.end()
    return src[:insert_pos] + SHORT_CIRCUIT + src[insert_pos:]

def patch_body_style(src: str) -> str:
    """
    Agents: activities, analytics, leads, notifications, orders
    Same — inject after "logger.info(f'Message:" line.
    """
    pattern = r"(    logger\.info\(f'Message:[^\n]*\n)"
    match = re.search(pattern, src)
    if not match:
        return src
    insert_pos = match.end()
    return src[:insert_pos] + SHORT_CIRCUIT + src[insert_pos:]

def patch_opportunities(src: str) -> str:
    """
    Opportunities has body_mode check already — inject before CASE 1 block.
    """
    anchor = "    # ── CASE 1:"
    if anchor not in src:
        # Fallback: inject after the Pre-Router logger line
        pattern = r"(    logger\.info\('=== Opportunity Pre-Router[^\n]*\n)"
        match = re.search(pattern, src)
        if not match:
            return src
        insert_pos = match.end()
        return src[:insert_pos] + SHORT_CIRCUIT_OPP + src[insert_pos:]
    idx = src.index(anchor)
    return src[:idx] + SHORT_CIRCUIT_OPP + src[idx:]


PATCH_FN = {
    "accounting":    patch_message_style,
    "accounts":      patch_message_style,
    "activities":    patch_body_style,
    "analytics":     patch_body_style,
    "contacts":      patch_message_style,
    "leads":         patch_body_style,
    "notifications": patch_body_style,
    "opportunities": patch_opportunities,
    "orders":        patch_body_style,
    "products":      patch_message_style,
}


def patch_file(path: Path, fn, label: str) -> bool:
    if not path.exists():
        print(f"  SKIP (missing) : {label}")
        return False
    src = read(path)
    if already_patched(src):
        print(f"  ALREADY DONE   : {label}")
        return False
    patched = fn(src)
    if patched == src:
        print(f"  NO CHANGE      : {label}  ← anchor not found!")
        return False
    write(path, patched)
    print(f"  PATCHED        : {label}")
    return True


if __name__ == "__main__":
    print(f"Base   : {BASE}")
    print(f"Exists : {BASE.exists()}\n")

    if not BASE.exists():
        print("ERROR: Base path does not exist.")
        raise SystemExit(1)

    count = 0
    for agent in AGENT_DIRS:
        path = BASE / agent / "pre_router.py"
        if patch_file(path, PATCH_FN[agent], f"{agent}/pre_router.py"):
            count += 1

    print(f"\n{count} file(s) patched.")
    print("\nCommit and push to Railway:")
    print("  git add app/agents/*/pre_router.py")
    print('  git commit -m "fix: add routerAction short-circuit to all pre_routers"')
    print("  git push")
    print("\nVerify (should now return accounts list, not Ollama error):")
    print('  Invoke-RestMethod -Uri "https://orbitcrm-production.up.railway.app/account-chat" `')
    print('    -Method POST -ContentType "application/json" `')
    print("    -Body '{\"chatInput\": {\"mode\": \"list\", \"routerAction\": true}, \"sessionId\": \"t1\"}'")
