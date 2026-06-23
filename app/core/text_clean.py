"""Shared text normalization for DB free-text (dash-fix and typographic cleanup).

Remote PostgreSQL may store en/em dashes, curly quotes, ellipses, etc. in
free-text fields. When the client_encoding doesn't match, each UTF-8 byte renders
as '?' — e.g. U+2013 EN DASH (3 bytes) becomes '???', so "Payment complete – INV-1"
shows as "Payment complete ??? INV-1". Formatters render the STRUCTURED object's
fields raw, so this normalizes them to plain ASCII.

`clean_text(s)`  — normalize a single string.
`clean_obj(obj)` — recursively normalize every string value in a dict/list (used
                   by each agent's formatter on the parsed SP result, so structured
                   detail views render clean regardless of the source encoding).

Originated in app/agents/activities/formatter.py; centralized here so all modules
share one implementation.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Typographic Unicode → safe ASCII equivalents (covers the cases that mangle).
_UNICODE_NORMALISE = str.maketrans({
    # Hyphens / dashes → ASCII hyphen-minus
    '­': '-', '‐': '-', '‑': '-', '‒': '-', '–': '-',
    '—': '-', '―': '-', '−': '-', '﹘': '-', '﹣': '-',
    '－': '-',
    # Curly / smart quotes → straight ASCII
    '‘': "'", '’': "'", '‚': "'", '‛': "'",
    '“': '"', '”': '"', '„': '"', '‟': '"',
    # Other common typographic chars
    '…': '...', '•': '*', '·': '*', '‣': '*', ' ': ' ',
})

# The post-mangling " ??? " (or " ?? ") literal that lands here when the bytes
# were already replaced with '?' before us.
_MANGLED_DASH_RE = re.compile(r' \?{2,3} ')


def clean_text(value: Optional[str]) -> Optional[str]:
    """Normalize a single string to ASCII (dashes, quotes, ellipsis, '???')."""
    if not value:
        return value
    return _MANGLED_DASH_RE.sub(' - ', str(value).translate(_UNICODE_NORMALISE))


def clean_obj(obj: Any) -> Any:
    """Recursively normalize every string VALUE in a dict/list. Keys, numbers,
    booleans, None, and other types are left unchanged. Returns a cleaned copy."""
    if isinstance(obj, str):
        return clean_text(obj)
    if isinstance(obj, dict):
        return {k: clean_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_obj(v) for v in obj]
    return obj
