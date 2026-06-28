"""
CEO Morning Briefing — a strategic, action-oriented daily email.

Answers "What requires my attention today to maximize growth and reduce risk?"
— not "what happened yesterday". Real CRM data only (no fabricated metrics).

Design notes:
  • Recipient is configured via CEO_BRIEFING_EMAIL — the CEO is an internal
    stakeholder, so their address lives in env config, NEVER in accounts/contacts.
  • This is an INTERNAL admin email; it does NOT go through the customer
    email-verification gate (_is_real_email) used by dunning/order emails, and is
    independent of AGENT_BUS_AUTOSEND.
  • Gated by CEO_BRIEFING_ENABLED; scheduled daily 08:00 ET from app/main.py.
  • Admin endpoints /ceo-briefing/{preview,send-now} for review before enabling.
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter

from app.core.database import get_connection

logger = logging.getLogger("ceo_briefing")


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


ENABLED   = _flag("CEO_BRIEFING_ENABLED")
RECIPIENT = (os.getenv("CEO_BRIEFING_EMAIL", "") or "").strip()


def _money(n) -> str:
    try:
        return "${:,.0f}".format(float(n or 0))
    except Exception:
        return "$0"


def _rows(cur, sql: str, params=None) -> List[tuple]:
    cur.execute(sql, params or ())
    return cur.fetchall()


def _one(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    r = cur.fetchone()
    return r if r else ()


# ── Data gathering ──────────────────────────────────────────────────────────────

def gather() -> Dict[str, Any]:
    """Pull the strategic numbers from real CRM tables."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            rev_yest = _one(cur, "SELECT COALESCE(SUM(amount),0) FROM payments "
                                 "WHERE payment_date::date = CURRENT_DATE - 1")[0]

            pipeline, weighted, open_cnt = _one(cur,
                "SELECT COALESCE(SUM(amount),0), "
                "       COALESCE(SUM(amount*COALESCE(probability,0)/100.0),0), COUNT(*) "
                "FROM opportunities WHERE status='open'")

            close_amt, close_weighted, close_cnt = _one(cur,
                "SELECT COALESCE(SUM(amount),0), "
                "       COALESCE(SUM(amount*COALESCE(probability,0)/100.0),0), COUNT(*) "
                "FROM opportunities WHERE status='open' "
                "  AND close_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7")

            ar_amt, ar_cnt = _one(cur,
                "SELECT COALESCE(SUM(computed_balance_due),0), COUNT(*) "
                "FROM accounting_invoice_pipeline "
                "WHERE payment_status IN ('unpaid','partial') AND due_date::date < CURRENT_DATE")

            slipped_amt, slipped_cnt = _one(cur,
                "SELECT COALESCE(SUM(amount),0), COUNT(*) FROM opportunities "
                "WHERE status='open' AND close_date < CURRENT_DATE")

            advocates = _one(cur,
                "SELECT COUNT(DISTINCT account_id) FROM opportunities "
                "WHERE status='closed_won' AND updated_at >= now() - interval '7 days'")[0]

            won_amt = _one(cur,
                "SELECT COALESCE(SUM(amount),0) FROM opportunities "
                "WHERE status='closed_won' AND updated_at >= now() - interval '7 days'")[0]

            closing = _rows(cur,
                "SELECT o.name, COALESCE(a.account_name,'—'), ROUND(o.amount::numeric,2), "
                "       COALESCE(o.probability,0), o.close_date "
                "FROM opportunities o LEFT JOIN accounts a ON a.account_id=o.account_id "
                "WHERE o.status='open' AND o.close_date BETWEEN CURRENT_DATE AND CURRENT_DATE + 7 "
                "ORDER BY o.amount DESC LIMIT 5")

            biggest = _rows(cur,
                "SELECT o.name, COALESCE(a.account_name,'—'), ROUND(o.amount::numeric,2), "
                "       o.stage, COALESCE(o.probability,0) "
                "FROM opportunities o LEFT JOIN accounts a ON a.account_id=o.account_id "
                "WHERE o.status='open' AND COALESCE(o.amount,0) > 0 "
                "ORDER BY o.amount DESC NULLS LAST LIMIT 5")

            atrisk = _rows(cur,
                "SELECT o.name, COALESCE(a.account_name,'—'), ROUND(o.amount::numeric,2), "
                "       (CURRENT_DATE - o.close_date) AS days "
                "FROM opportunities o LEFT JOIN accounts a ON a.account_id=o.account_id "
                "WHERE o.status='open' AND o.close_date < CURRENT_DATE "
                "ORDER BY o.amount DESC LIMIT 5")

            big_inv = _rows(cur,
                "SELECT v.invoice_number, COALESCE(a.account_name,'—'), "
                "       ROUND(v.computed_balance_due::numeric,2), (CURRENT_DATE - v.due_date::date) AS days "
                "FROM accounting_invoice_pipeline v LEFT JOIN accounts a ON a.account_id=v.account_id "
                "WHERE v.payment_status IN ('unpaid','partial') AND v.due_date::date < CURRENT_DATE "
                "ORDER BY v.computed_balance_due DESC LIMIT 3")
        return {
            "rev_yest": rev_yest, "pipeline": pipeline, "weighted": weighted, "open_cnt": open_cnt,
            "close_amt": close_amt, "close_weighted": close_weighted, "close_cnt": close_cnt,
            "ar_amt": ar_amt, "ar_cnt": ar_cnt, "slipped_amt": slipped_amt, "slipped_cnt": slipped_cnt,
            "advocates": advocates, "won_amt": won_amt,
            "closing": closing, "biggest": biggest, "atrisk": atrisk, "big_inv": big_inv,
        }
    finally:
        conn.close()


def _decision(d: Dict[str, Any]) -> str:
    """The single most important decision: biggest at-risk deal vs biggest overdue invoice."""
    deal = d["atrisk"][0] if d["atrisk"] else None
    inv  = d["big_inv"][0] if d["big_inv"] else None
    deal_amt = float(deal[2]) if deal else 0
    inv_amt  = float(inv[2])  if inv  else 0
    if deal_amt == 0 and inv_amt == 0:
        return "No critical risk today — focus on advancing the largest open deal."
    if deal_amt >= inv_amt:
        return (f"Re-engage **{deal[1]}** on the slipped deal “{deal[0]}” "
                f"({_money(deal[2])}, {deal[3]} days past close) before it decays.")
    return (f"Chase **{inv[1]}** on overdue invoice {inv[0]} "
            f"({_money(inv[2])}, {inv[3]} days overdue).")


# ── Rendering ───────────────────────────────────────────────────────────────────

def render(d: Dict[str, Any]) -> Dict[str, str]:
    today = datetime.now().strftime("%B %-d, %Y") if os.name != "nt" else datetime.now().strftime("%B %d, %Y")
    at_risk_total = float(d["ar_amt"] or 0) + float(d["slipped_amt"] or 0)
    decision = _decision(d)

    # ── plain text ──
    t: List[str] = []
    t.append(f"MORNING CEO BRIEFING — {today}")
    t.append("")
    t.append("THE FIVE NUMBERS")
    t.append(f"  1. Revenue captured yesterday : {_money(d['rev_yest'])}")
    t.append(f"  2. Revenue at risk           : {_money(at_risk_total)}  "
             f"({_money(d['ar_amt'])} overdue AR + {_money(d['slipped_amt'])} slipped deals)")
    t.append(f"  3. Likely to close this week : {_money(d['close_weighted'])} weighted "
             f"({_money(d['close_amt'])} gross, {d['close_cnt']} deals)")
    t.append(f"  4. New advocates (won, 7d)   : {d['advocates']} accounts ({_money(d['won_amt'])})")
    t.append(f"  5. #1 decision today         : {decision}")
    t.append("")
    t.append("1. REVENUE SNAPSHOT")
    t.append(f"   Active pipeline      : {_money(d['pipeline'])} ({d['open_cnt']} open)")
    t.append(f"   Weighted forecast    : {_money(d['weighted'])}")
    t.append(f"   Closing this week    : {_money(d['close_amt'])} ({d['close_cnt']} deals)")
    t.append(f"   Captured yesterday   : {_money(d['rev_yest'])}")
    t.append("")
    t.append("2. REVENUE AT RISK")
    t.append(f"   Overdue AR: {_money(d['ar_amt'])} across {d['ar_cnt']} invoices")
    t.append(f"   Slipped deals: {_money(d['slipped_amt'])} across {d['slipped_cnt']} opportunities")
    for r in d["atrisk"]:
        t.append(f"     - {r[0]} ({r[1]}) — {_money(r[2])}, {r[3]}d past close")
    t.append("")
    t.append("3. LIKELY TO CLOSE THIS WEEK")
    for r in d["closing"]:
        t.append(f"   - {r[0]} ({r[1]}) — {_money(r[2])} @ {int(r[3])}% · {r[4]}")
    if not d["closing"]:
        t.append("   (none scheduled to close in the next 7 days)")
    t.append("")
    t.append("4. GROWTH — BIGGEST DEALS IN PLAY")
    for r in d["biggest"]:
        t.append(f"   - {r[0]} ({r[1]}) — {_money(r[2])} · {r[3]} @ {int(r[4])}%")
    t.append("")
    t.append("5. CRITICAL EVENTS")
    for r in d["big_inv"]:
        flag = "  ⚠ >$25k & 45d+" if float(r[2]) > 25000 and int(r[3]) >= 45 else ""
        t.append(f"   - Overdue invoice {r[0]} — {r[1]}: {_money(r[2])}, {r[3]}d overdue{flag}")
    t.append("")
    t.append(f"#1 CEO ACTION: {decision}")
    t.append("")
    t.append("— Conscestra CRM · the orchestration of customer intelligence")
    text = "\n".join(t).replace("**", "")

    # ── HTML ──
    def card(num, label, val, sub=""):
        return (f'<td style="padding:10px 14px;background:#f6f8fc;border-radius:10px;vertical-align:top;">'
                f'<div style="font-size:11px;color:#8a93a6;text-transform:uppercase;letter-spacing:.04em;">{num}. {label}</div>'
                f'<div style="font-size:20px;font-weight:800;color:#16213e;margin-top:2px;">{val}</div>'
                f'<div style="font-size:11px;color:#8a93a6;margin-top:2px;">{sub}</div></td>')

    def li_rows(rows, fmt):
        return "".join(f'<li style="margin:3px 0;">{fmt(r)}</li>' for r in rows) or \
               '<li style="color:#8a93a6;">None.</li>'

    h: List[str] = []
    h.append('<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:680px;margin:0 auto;color:#1f2738;">')
    h.append(f'<h1 style="font-size:20px;margin:0 0 2px;">🌅 Morning CEO Briefing</h1>')
    h.append(f'<div style="color:#8a93a6;font-size:13px;margin-bottom:14px;">{today} · Conscestra CRM</div>')
    h.append('<table style="width:100%;border-collapse:separate;border-spacing:8px 0;margin-bottom:6px;"><tr>')
    h.append(card(1, "Captured yesterday", _money(d['rev_yest'])))
    h.append(card(2, "Revenue at risk", _money(at_risk_total), f"{_money(d['ar_amt'])} AR + {_money(d['slipped_amt'])} deals"))
    h.append(card(3, "Likely to close (wk)", _money(d['close_weighted']), f"{d['close_cnt']} deals, weighted"))
    h.append('</tr><tr><td style="height:8px"></td></tr><tr>')
    h.append(card(4, "New advocates (7d)", str(d['advocates']), _money(d['won_amt'])))
    h.append(f'<td colspan="2" style="padding:10px 14px;background:#fff7ed;border-radius:10px;">'
             f'<div style="font-size:11px;color:#b45309;text-transform:uppercase;letter-spacing:.04em;">5. #1 decision today</div>'
             f'<div style="font-size:14px;font-weight:600;color:#7c2d12;margin-top:3px;">{decision.replace("**","")}</div></td>')
    h.append('</tr></table>')

    def section(title, inner):
        return (f'<h2 style="font-size:15px;margin:18px 0 6px;border-bottom:2px solid #eef1f6;padding-bottom:4px;">{title}</h2>{inner}')

    h.append(section("1 · Revenue Snapshot",
        f'<ul style="margin:0;padding-left:18px;font-size:13px;">'
        f'<li>Active pipeline: <b>{_money(d["pipeline"])}</b> ({d["open_cnt"]} open)</li>'
        f'<li>Weighted forecast: <b>{_money(d["weighted"])}</b></li>'
        f'<li>Closing this week: <b>{_money(d["close_amt"])}</b> ({d["close_cnt"]} deals)</li>'
        f'<li>Captured yesterday: <b>{_money(d["rev_yest"])}</b></li></ul>'))

    h.append(section("2 · Revenue at Risk",
        f'<div style="font-size:13px;">Overdue AR <b>{_money(d["ar_amt"])}</b> ({d["ar_cnt"]} invoices) · '
        f'Slipped deals <b>{_money(d["slipped_amt"])}</b> ({d["slipped_cnt"]})</div>'
        f'<ul style="margin:6px 0 0;padding-left:18px;font-size:13px;">'
        + li_rows(d["atrisk"], lambda r: f'{r[0]} <span style="color:#8a93a6">({r[1]})</span> — <b>{_money(r[2])}</b>, {r[3]}d past close')
        + '</ul>'))

    h.append(section("3 · Likely to Close This Week",
        '<ul style="margin:0;padding-left:18px;font-size:13px;">'
        + li_rows(d["closing"], lambda r: f'{r[0]} <span style="color:#8a93a6">({r[1]})</span> — <b>{_money(r[2])}</b> @ {int(r[3])}% · {r[4]}')
        + '</ul>'))

    h.append(section("4 · Growth — Biggest Deals in Play",
        '<ul style="margin:0;padding-left:18px;font-size:13px;">'
        + li_rows(d["biggest"], lambda r: f'{r[0]} <span style="color:#8a93a6">({r[1]})</span> — <b>{_money(r[2])}</b> · {r[3]} @ {int(r[4])}%')
        + '</ul>'))

    h.append(section("5 · Critical Events",
        '<ul style="margin:0;padding-left:18px;font-size:13px;">'
        + li_rows(d["big_inv"], lambda r: (f'Overdue invoice {r[0]} <span style="color:#8a93a6">({r[1]})</span> — '
                  f'<b>{_money(r[2])}</b>, {r[3]}d overdue'
                  + (' <span style="color:#b91c1c;font-weight:700">⚠ &gt;$25k &amp; 45d+</span>' if float(r[2])>25000 and int(r[3])>=45 else '')))
        + '</ul>'))

    h.append(f'<div style="margin-top:18px;padding:12px 14px;background:#eef6ff;border-radius:10px;font-size:14px;">'
             f'<b>#1 CEO action today:</b> {decision.replace("**","")}</div>')
    h.append('<div style="margin-top:16px;color:#9aa3b2;font-size:11px;">Conscestra CRM — the orchestration of customer intelligence. '
             'Reply to this email to ask the Orchestrator a follow-up.</div>')
    h.append('</div>')

    # Plain-ASCII subject (no $/·/em-dash) — shared-host spam filters down-rank
    # currency symbols and non-ASCII in headers; the detail lives in the body.
    subject = f"Morning CEO Briefing - {today}"
    return {"subject": subject, "html": "".join(h), "text": text}


def build_briefing() -> Dict[str, str]:
    return render(gather())


# ── Send ────────────────────────────────────────────────────────────────────────

def send_briefing(force: bool = False) -> Dict[str, Any]:
    """Compose + email the CEO briefing. Gated by CEO_BRIEFING_ENABLED unless force.
    Internal email — bypasses the customer verification gate by design."""
    if not ENABLED and not force:
        return {"enabled": False, "skipped": True}
    if not RECIPIENT:
        return {"error": "CEO_BRIEFING_EMAIL not set"}
    msg = build_briefing()
    try:
        from app.agents.email.smtp_imap import send_email
        res = send_email(RECIPIENT, msg["subject"], msg["html"], msg["text"],
                         from_name="Conscestra CRM · Orchestrator")
        ok = bool(res.get("success", True)) if isinstance(res, dict) else True
        logger.info(f"[ceo_briefing] sent to {RECIPIENT}: {msg['subject']}")
        return {"sent": ok, "to": RECIPIENT, "subject": msg["subject"]}
    except Exception as exc:
        logger.error(f"[ceo_briefing] send failed: {exc}", exc_info=True)
        return {"error": str(exc)}


# ── Admin endpoints ───────────────────────────────────────────────────────────────

router = APIRouter(tags=["ceo-briefing"])


@router.get("/ceo-briefing/status")
def ceo_briefing_status():
    return {"enabled": ENABLED, "recipient_configured": bool(RECIPIENT)}


@router.get("/ceo-briefing/preview")
def ceo_briefing_preview():
    """Render the briefing WITHOUT sending (HTML + text). Admin-gated."""
    return build_briefing()


@router.post("/ceo-briefing/send-now")
async def ceo_briefing_send_now():
    """Send the briefing now (force, regardless of the enabled flag). Admin-gated."""
    import asyncio
    return await asyncio.to_thread(send_briefing, True)
