"""Build the client-facing contact directory page from readiness.json.

Takes the JSON from scripts/export_readiness.py, maps it to the compact
payload keys the page's JS expects, and injects it into
scripts/report_template.html (single-file page: embedded payload + vanilla
JS paging/sort/filter). The template holds __DATA__, __STATS__, __DATE__
placeholders and nothing else dynamic.

Client rules baked into the page (2026-09-21): no scores shown, no
"signals" jargon, footer robots.txt/verify-before-send line is CASL cover -
do not remove. Verify JS by extracting <script> and running under node with
a stub document, not by eyeballing.

Usage: python scripts/build_report.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "report_template.html"
SRC = ROOT / "data" / "reports" / "readiness.json"
OUT = ROOT / "data" / "reports" / "outreach_readiness.html"


def payload_key(org: dict) -> dict:
    # keys the page JS reads: n name, c city, p province, e email,
    # ph phone, w website, s social, v score (never displayed)
    return {
        "n": org["name"],
        "c": org.get("city") or "",
        "p": (org.get("province") or "").upper(),
        "e": org.get("email") or "",
        "ph": org.get("phone") or "",
        "w": org.get("website") or "",
        "s": org.get("social") or {},
        "v": org.get("score", 0),
    }


def main() -> None:
    orgs = json.loads(SRC.read_text(encoding="utf-8"))
    rows = [payload_key(o) for o in orgs]
    # contact-first order: email, then phone, then social breadth, then name
    rows.sort(key=lambda r: (
        0 if r["e"] else 1,
        0 if r["ph"] else 1,
        -len(r["s"]),
        r["n"].lower(),
    ))

    with_email = sum(1 for r in rows if r["e"])
    with_social = sum(1 for r in rows if r["s"])
    # "full" = the 80+ readiness band, same definition as the band filter
    full = sum(1 for r in rows if r["v"] >= 80)
    stats = (
        f"<b>{len(rows)}</b> organisations &middot; <b>{with_email}</b> with verified email\n"
        f"  &middot; <b>{with_social}</b> with social channels &middot; <b>{full}</b> with email, phone and\n"
        f"  social"
    )

    html = TEMPLATE.read_text(encoding="utf-8")
    today = date.today()
    date_str = f"{today.strftime('%B')} {today.day}, {today.year}"
    html = html.replace("__STATS__", stats)
    html = html.replace("__DATE__", date_str)
    html = html.replace("__DATA__", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
    OUT.write_text(html, encoding="utf-8")
    print(f"{len(rows)} orgs ({with_email} email, {with_social} social, {full} full) -> {OUT}")


if __name__ == "__main__":
    main()
