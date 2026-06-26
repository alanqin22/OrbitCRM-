"""Lead / company enrichment — the project's first OUTWARD 'function call'.

IBM's article notes agents "use function calling to connect with external tools —
APIs, data sources, web searches." Every agent here so far reads the CRM DB; this
module lets the Leads agent reach BEYOND it to fill knowledge gaps (firmographics
for a new lead). Stub by default (deterministic, no network, safe). Point
LEADS_ENRICH_API_URL at a real provider (Clearbit / Apollo / People Data Labs / …)
and adapt `_call_api()` to its response shape to go live.

CONFIG (env)
  LEADS_ENRICH_API_URL   ''   real enrichment endpoint ('{domain}' is substituted,
                              else added as ?domain=). Unset -> deterministic stub.
  LEADS_ENRICH_API_KEY   ''   bearer token for that endpoint
  LEADS_ENRICH_TIMEOUT   6    request timeout (seconds)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("enrichment")

ENRICH_API_URL = os.getenv("LEADS_ENRICH_API_URL", "").strip()
ENRICH_API_KEY = os.getenv("LEADS_ENRICH_API_KEY", "").strip()
ENRICH_TIMEOUT = float(os.getenv("LEADS_ENRICH_TIMEOUT", "6"))

_INDUSTRIES = ["Software", "Manufacturing", "Healthcare", "Financial Services",
               "Retail", "Logistics", "Construction", "Education", "Hospitality",
               "Energy", "Professional Services", "Media & Marketing"]
_EMPLOYEES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1001-5000", "5000+"]
_REVENUE = ["<$1M", "$1M-$10M", "$10M-$50M", "$50M-$250M", "$250M-$1B", "$1B+"]
_LOCATIONS = ["Toronto, ON", "Vancouver, BC", "Montreal, QC", "Calgary, AB",
              "Ottawa, ON", "Waterloo, ON", "Halifax, NS", "Edmonton, AB"]

_SLUG = re.compile(r"[^a-z0-9]+")


def _domain(email: Optional[str], company: Optional[str]) -> str:
    if email and "@" in email:
        return email.split("@", 1)[1].strip().lower()
    if company:
        slug = _SLUG.sub("", company.strip().lower())
        return f"{slug}.com" if slug else ""
    return ""


def enrich_company(company: Optional[str] = None, email: Optional[str] = None,
                   domain: Optional[str] = None) -> Dict[str, Any]:
    """Return firmographics for a company. Tries the live API if configured, else a
    deterministic stub. Never raises — returns {'matched': False} when there's
    nothing to look up or the lookup fails."""
    seed = (domain or _domain(email, company) or (company or "")).strip().lower()
    if not seed:
        return {"matched": False, "source": "none", "reason": "no company/email/domain"}
    if ENRICH_API_URL:
        try:
            return _call_api(seed)
        except Exception as exc:  # network/parse errors fall back to the stub
            logger.warning(f"[enrichment] live API failed ({exc}); using stub")
    return _stub(seed, company)


def _stub(seed: str, company: Optional[str]) -> Dict[str, Any]:
    """Deterministic pseudo-firmographics — stable per company, no network."""
    h = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
    return {
        "matched": True,
        "source": "stub",
        "company": company,
        "domain": seed,
        "website": f"https://{seed}",
        "industry": _INDUSTRIES[h % len(_INDUSTRIES)],
        "employee_band": _EMPLOYEES[(h >> 5) % len(_EMPLOYEES)],
        "revenue_band": _REVENUE[(h >> 9) % len(_REVENUE)],
        "hq_location": _LOCATIONS[(h >> 13) % len(_LOCATIONS)],
        "confidence": round(0.60 + (h % 36) / 100.0, 2),
    }


def apply_to_lead(lead_id: str, data: Dict[str, Any]) -> int:
    """Write enrichment onto the lead row, GAP-FILL only (existing values are never
    overwritten). Maps hq_location 'City, PROV' -> city/province. Returns rows
    updated. Requires sql/leads_enrichment_columns.sql — raises if columns absent
    (callers treat enrichment-apply as best-effort)."""
    if not data or not data.get("matched"):
        return 0
    from app.core.database import get_connection
    hq = (data.get("hq_location") or "")
    city = prov = None
    if "," in hq:
        city, prov = [x.strip() for x in hq.split(",", 1)]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE leads SET
                    industry      = COALESCE(NULLIF(industry, ''),      %(industry)s),
                    website       = COALESCE(NULLIF(website, ''),       %(website)s),
                    employee_band = COALESCE(NULLIF(employee_band, ''), %(emp)s),
                    revenue_band  = COALESCE(NULLIF(revenue_band, ''),  %(rev)s),
                    city          = COALESCE(NULLIF(city, ''),          %(city)s),
                    province      = COALESCE(NULLIF(province, ''),      %(prov)s),
                    enriched_at   = now(),
                    updated_at    = now()
                WHERE lead_id = %(id)s
                """,
                {"industry": data.get("industry"), "website": data.get("website"),
                 "emp": data.get("employee_band"), "rev": data.get("revenue_band"),
                 "city": city, "prov": prov, "id": lead_id},
            )
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def _call_api(seed: str) -> Dict[str, Any]:
    """Call the configured provider. ADAPT the response mapping to your provider."""
    q = urllib.parse.quote(seed)
    url = (ENRICH_API_URL.replace("{domain}", q) if "{domain}" in ENRICH_API_URL
           else f"{ENRICH_API_URL}{'&' if '?' in ENRICH_API_URL else '?'}domain={q}")
    headers = {"Accept": "application/json"}
    if ENRICH_API_KEY:
        headers["Authorization"] = f"Bearer {ENRICH_API_KEY}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=ENRICH_TIMEOUT) as r:
        raw = json.loads(r.read().decode("utf-8"))
    return {
        "matched": True,
        "source": "api",
        "domain": seed,
        "website": raw.get("website") or f"https://{seed}",
        "industry": raw.get("industry"),
        "employee_band": raw.get("employee_band") or raw.get("employees"),
        "revenue_band": raw.get("revenue_band") or raw.get("revenue"),
        "hq_location": raw.get("hq_location") or raw.get("location"),
        "confidence": raw.get("confidence", 0.9),
        "raw": raw,
    }
