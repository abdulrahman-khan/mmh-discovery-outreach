"""Import Muslim places of worship from OSM Overpass into org_candidates.

Dry-run by default: writes data/runs/<ts>/osm_candidates.json and prints a
coverage summary. --write-db upserts org_candidates (needs DATABASE_URL).
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from mmh_discovery import config

QUERY = """
[out:json][timeout:120];
area["ISO3166-1"="CA"][admin_level=2]->.ca;
(
  node["amenity"="place_of_worship"]["religion"="muslim"](area.ca);
  way["amenity"="place_of_worship"]["religion"="muslim"](area.ca);
);
out center tags;
"""

PROVINCES = {
    "alberta": "AB", "ab": "AB",
    "british columbia": "BC", "bc": "BC",
    "manitoba": "MB", "mb": "MB",
    "new brunswick": "NB", "nb": "NB",
    "newfoundland and labrador": "NL", "newfoundland": "NL", "nl": "NL",
    "northwest territories": "NT", "nt": "NT",
    "nova scotia": "NS", "ns": "NS",
    "nunavut": "NU", "nu": "NU",
    "ontario": "ON", "on": "ON",
    "prince edward island": "PE", "pe": "PE",
    "quebec": "QC", "qc": "QC",
    "saskatchewan": "SK", "sk": "SK",
    "yukon": "YT", "yt": "YT",
}

SOCIAL_PLATFORMS = ("facebook", "instagram", "twitter", "youtube", "tiktok", "whatsapp")


def normalize_province(raw: str | None) -> str | None:
    if not raw:
        return None
    return PROVINCES.get(raw.strip().lower())


def parse_element(el: dict) -> dict:
    tags = el.get("tags", {})
    center = el.get("center", {})
    social = {}
    for platform in SOCIAL_PLATFORMS:
        for key in (f"contact:{platform}", platform):
            if tags.get(key):
                social[platform] = tags[key]
                break
    street = " ".join(
        p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p
    ) or None
    return {
        "source_id": "osm",
        "external_id": f"{el['type']}/{el['id']}",
        "name": tags.get("name") or tags.get("name:en"),
        "phone": tags.get("contact:phone") or tags.get("phone"),
        "email": tags.get("contact:email") or tags.get("email"),
        "website": tags.get("contact:website") or tags.get("website"),
        "address_line1": street,
        "city": tags.get("addr:city"),
        "province": normalize_province(tags.get("addr:province")),
        "postal_code": tags.get("addr:postcode"),
        "lat": el.get("lat", center.get("lat")),
        "lng": el.get("lon", center.get("lon")),
        "social": social,
        "raw": tags,
    }


def fetch() -> list[dict]:
    resp = httpx.post(
        config.OVERPASS_URL,
        data={"data": QUERY},
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.OVERPASS_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return [parse_element(el) for el in resp.json().get("elements", [])]


def upsert(candidates: list[dict]) -> int:
    import psycopg
    from psycopg.rows import dict_row

    rows = [
        (
            c["source_id"], c["external_id"], c["name"], c["phone"], c["email"],
            c["website"], c["address_line1"], c["city"], c["province"],
            c["postal_code"], c["lat"], c["lng"],
            json.dumps(c["social"]), json.dumps(c["raw"]),
        )
        for c in candidates
    ]
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn, conn.transaction():
        conn.executemany(
            """
            insert into org_candidates (
                source_id, external_id, name, phone, email, website,
                address_line1, city, province, postal_code, lat, lng,
                social, raw
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            on conflict (source_id, external_id) do update set
                name = coalesce(excluded.name, org_candidates.name),
                phone = coalesce(excluded.phone, org_candidates.phone),
                email = coalesce(excluded.email, org_candidates.email),
                website = coalesce(excluded.website, org_candidates.website),
                city = coalesce(excluded.city, org_candidates.city),
                province = coalesce(excluded.province, org_candidates.province),
                social = excluded.social,
                raw = excluded.raw
            """,
            rows,
        )
    return len(rows)


def print_summary(candidates: list[dict]) -> None:
    n = len(candidates)
    with_website = sum(1 for c in candidates if c["website"])
    with_phone = sum(1 for c in candidates if c["phone"])
    with_email = sum(1 for c in candidates if c["email"])
    with_province = sum(1 for c in candidates if c["province"])
    named = sum(1 for c in candidates if c["name"])
    print(f"elements:     {n}")
    print(f"name:         {named} ({named / n:.0%})")
    print(f"website:      {with_website} ({with_website / n:.0%})")
    print(f"phone:        {with_phone} ({with_phone / n:.0%})")
    print(f"email:        {with_email} ({with_email / n:.0%})")
    print(f"province:     {with_province} ({with_province / n:.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-db", action="store_true", help="upsert into org_candidates")
    args = parser.parse_args()

    candidates = fetch()

    run_dir = Path("data/runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    out_file = run_dir / "osm_candidates.json"
    out_file.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_file}")
    print_summary(candidates)

    if args.write_db:
        if not config.DATABASE_URL:
            raise SystemExit("--write-db requires DATABASE_URL")
        print(f"upserted {upsert(candidates)} candidates")


if __name__ == "__main__":
    main()
