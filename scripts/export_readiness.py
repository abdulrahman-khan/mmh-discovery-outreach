"""Export outreach-readiness scores for all organizations.

Score (0-100) = how reachable + how ready for a mail-merge campaign:
  reachable primary channel  email 45, phone 25, on-site contact form 20 (max 45)
  channel breadth            +10 per extra contact channel type
  social presence            +5 per platform (engagement/verification channel)
  mail-merge completeness    +10 city, +10 postal code
  evidence quality           +10 if email evidence uses the v2 extractor prompt
  provenance quality         +10 if the email's evidence page is a contact page
Dry JSON is written to data/reports/readiness.json (git-ignored data dir).

Usage: python scripts/export_readiness.py
"""
from __future__ import annotations

import json
from pathlib import Path

import psycopg

from mmh_discovery import config

QUERY = """
with kinds as (
    select c.org_id,
           bool_or(c.kind = 'email')        as has_email,
           bool_or(c.kind = 'phone')        as has_phone,
           bool_or(c.kind = 'contact_form') as has_form
    from contacts c
    group by c.org_id
)
select o.id, o.name, o.website, o.email, o.phone, o.city, o.province,
       o.postal_code, o.social,
       coalesce((
           select string_agg(distinct fp.method, ',')
           from field_provenance fp
           join contacts c on c.id = fp.entity_id
           where fp.entity_type = 'contact' and fp.field = 'email'
             and c.org_id = o.id
       ), '') as email_methods,
       coalesce((
           select bool_or(sr.url ilike '%contact%')
           from field_provenance fp
           join contacts c on c.id = fp.entity_id
           join source_records sr on sr.id = fp.source_record_id
           where fp.entity_type = 'contact' and fp.field = 'email'
             and c.org_id = o.id
       ), false) as email_from_contact_page,
       exists (select 1 from kinds k
               where k.org_id = o.id and k.has_email)    as contact_email,
       exists (select 1 from kinds k
               where k.org_id = o.id and k.has_phone)    as contact_phone,
       exists (select 1 from kinds k
               where k.org_id = o.id and k.has_form)     as contact_form,
       (select max(sr.fetched_at) from contacts c
          join field_provenance fp on fp.entity_id = c.id
          join source_records sr on sr.id = fp.source_record_id
         where c.org_id = o.id)                          as last_evidence
from organizations o
where o.status <> 'merged' and o.merged_into is null
"""


def score(row) -> tuple[int, list[str]]:
    (oid, name, website, email, phone, city, province, postal, social,
     methods, from_contact, c_email, c_phone, c_form, last_ev) = row
    pts, reasons = 0, []

    channel = (45 if c_email else 0) + (25 if c_phone else 0) + (20 if c_form else 0)
    channel = min(channel, 45)
    if channel:
        pts += channel
        reasons.append("reachable")
    n_channels = sum([c_email, c_phone, c_form])
    if n_channels >= 2:
        pts += 10
        reasons.append("multi-channel")
    n_social = len(social or {})
    if n_social:
        pts += min(5 * n_social, 10)
        reasons.append("social")
    if city:
        pts += 10
    if postal:
        pts += 10
    if email and "v2" in methods:
        pts += 10
        reasons.append("fresh evidence")
    elif email:
        pts += 5
    if email and from_contact:
        pts += 10
        reasons.append("email from contact page")
    # bonus: email address matches the org's own domain (not a gmail inbox)
    if email and website:
        import re
        host = re.sub(r"^https?://(www\.)?", "", website).split("/")[0].lower()
        dom = email.split("@")[-1].lower()
        if host and (dom == host or host.endswith("." + dom) or dom.endswith("." + host)):
            pts += 5
            reasons.append("org-domain email")
    return min(pts, 100), reasons


def main() -> int:
    with psycopg.connect(config.DATABASE_URL) as conn:
        rows = conn.execute(QUERY).fetchall()
    out = []
    for r in rows:
        pts, reasons = score(r)
        out.append({
            "name": r[1], "website": r[2], "email": r[3], "phone": r[4],
            "city": r[5], "province": r[6], "postal": r[7], "social": r[8] or {},
            "score": pts, "reasons": reasons,
            "evidence": r[14].isoformat() if r[14] else None,
        })
    out.sort(key=lambda x: (-x["score"], x["name"].lower()))
    dest = Path(config.DATA_DIR) / "reports"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "readiness.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    n_email = sum(1 for o in out if o["email"])
    print(f"{len(out)} orgs, {n_email} with email -> {path}")
    bands = {"80+": 0, "60-79": 0, "40-59": 0, "<40": 0}
    for o in out:
        s = o["score"]
        bands["80+" if s >= 80 else "60-79" if s >= 60 else "40-59" if s >= 40 else "<40"] += 1
    print("bands:", bands)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
