"""Build the client-facing search-leads report: confirmed vs needs-review.

One page, two tabs, from the enrichment_proposals table:
  Tab 1 "Confirmed"   - values that passed a strong rule: email on the org's
                        own domain or own pages, postal/province from the org's
                        own site, city agreeing with our curated city table.
                        (Applied rows live in the main directory; shown here
                        with their evidence.)
  Tab 2 "Needs review" - same kind of values but weaker provenance: found on
                        third-party pages, or unconfirmed by any rule.

Confidence wording is client-facing only; the raw vet_rule stays in the
database. Template holds __DATA__/__STATS__/__DATE__ and nothing else
dynamic (same pattern as build_report.py).

Usage: python scripts/build_prospects_report.py
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import psycopg

from mmh_discovery import config

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "prospects_template.html"
OUT = Path(config.DATA_DIR) / "reports" / "search_leads.html"

QUERY = """
select coalesce(o.name, oc.name, p.domain, 'Unknown organisation') as org,
       p.domain,
       p.field,
       p.proposed_value,
       p.source_url,
       p.vetting,
       p.vetting || ':' || coalesce(p.vet_rule, 'unreviewed_field') as rule,
       p.status
from enrichment_proposals p
left join organizations o on o.id = p.org_id
left join org_candidates oc on oc.id = p.candidate_id
where p.status <> 'dismissed'
"""

# client-facing wording, keyed by vet_rule (never shows jargon)
RULE_LABEL = {
    "email_domain_match": ("confirmed", "Email on the organisation's own domain"),
    "email_on_own_page": ("confirmed", "Email published on the organisation's own pages"),
    "phone_on_own_page": ("confirmed", "Phone published on the organisation's own pages"),
    "fsa_own_page": ("confirmed", "Postal code on the organisation's own pages"),
    "province_fsa_own_page": ("confirmed", "Province derived from that postal code"),
    "city_table_agrees": ("confirmed", "City matches our Canadian city records"),
    "email_third_party": ("review", "Email found on a third-party page"),
    "phone_third_party": ("review", "Phone found on a third-party page"),
    "city_snippet_unconfirmed": ("review", "City from a search snippet, unconfirmed"),
    "city_unknown": ("review", "City not in our records"),
    "city_known_needs_pair": ("review", "City needs a matching province"),
    "province_snippet": ("review", "Province from a search snippet, unconfirmed"),
    "unreviewed_field": ("review", "Not yet checked by a rule"),
}

FIELD_LABEL = {"email": "Email", "phone": "Phone", "city": "City",
               "province": "Province", "postal_code": "Postal code",
               "website": "Website"}


def host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url or "").split("/")[0].lower()


def rows_from(query_result) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for org, domain, field, value, url, vetting, rule, status in query_result:
        rule = rule.split(":", 1)[1]
        level, why = RULE_LABEL.get(rule, RULE_LABEL["unreviewed_field"])
        # same value proposed twice (verified + proposed) -> keep the strong one
        key = (org.lower(), field, value.lower())
        row = {
            "o": org, "f": FIELD_LABEL.get(field, field), "v": value,
            "u": url or "", "h": host(url) or host(domain) or "",
            "l": level, "w": why, "a": status == "applied",
        }
        prev = seen.get(key)
        if prev is None or (prev["l"] == "review" and level == "confirmed"):
            seen[key] = row
    rows = list(seen.values())
    rows.sort(key=lambda r: (r["l"] != "confirmed", r["o"].lower(), r["f"]))
    return rows


def main() -> int:
    with psycopg.connect(config.DATABASE_URL, connect_timeout=15) as conn:
        data = conn.execute(QUERY).fetchall()
    rows = rows_from(data)

    n_conf = sum(1 for r in rows if r["l"] == "confirmed")
    stats = (
        f"<b>{len(rows)}</b> leads from the web search pass &middot; "
        f"<b>{n_conf}</b> confirmed &middot; <b>{len(rows) - n_conf}</b> need review"
    )

    html = TEMPLATE.read_text(encoding="utf-8")
    today = date.today()
    html = html.replace("__STATS__", stats)
    html = html.replace("__DATE__", f"{today.strftime('%B')} {today.day}, {today.year}")
    html = html.replace("__DATA__", json.dumps(rows, ensure_ascii=False,
                                               separators=(",", ":")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"{len(rows)} leads ({n_conf} confirmed, {len(rows) - n_conf} review) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
