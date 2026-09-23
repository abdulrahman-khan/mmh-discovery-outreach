"""Import mosques from the Overture Maps places release into org_candidates.

Reads the public GeoParquet release over HTTPS with DuckDB (no download, no
account): row-group bbox stats prune the scan to the target region. Dry-run
by default: writes data/runs/<ts>/overture_candidates.json and prints a
coverage summary. --write-db upserts org_candidates (needs DATABASE_URL).
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from mmh_discovery import config
from mmh_discovery.discovery.candidates import upsert
from mmh_discovery.discovery.osm import PROVINCES

BUCKET = "s3://overturemaps-us-west-2"
STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"
# Canada-ish bbox; DuckDB prunes to the intersecting continent tiles.
CANADA_BBOX = (-141.0, -52.0, 41.0, 84.0)
PROVINCE_BY_CODE = {v: k for k, v in PROVINCES.items()}


def latest_release() -> str:
    import duckdb

    con = duckdb.connect()
    return con.execute(f"select latest from '{STAC_CATALOG}'").fetchone()[0]


def fetch(release: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    import duckdb

    xmin, xmax, ymin, ymax = bbox
    base = f"{BUCKET}/release/{release}/theme=places/type=place/*"
    con = duckdb.connect()
    con.execute("install httpfs; load httpfs;")
    con.execute("set s3_region='us-west-2';")
    rows = con.execute(
        f"""
        select id,
               names.primary                                as name,
               websites[1]                                  as website,
               phones[1]                                    as phone,
               emails[1]                                    as email,
               addresses[1].freeform                        as freeform,
               addresses[1].locality                        as locality,
               addresses[1].region                          as region,
               addresses[1].postcode                        as postcode,
               (bbox.xmin + bbox.xmax) / 2                  as lng,
               (bbox.ymin + bbox.ymax) / 2                  as lat,
               socials,
               confidence
        from read_parquet('{base}')
        where (categories.primary = 'mosque'
               or list_contains(categories.alternate, 'mosque'))
          and bbox.xmin between ? and ? and bbox.ymin between ? and ?
          and addresses[1].country = 'CA'
        order by id
        """,
        [xmin, xmax, ymin, ymax],
    ).fetchall()
    return [parse_row(r) for r in rows]


def parse_row(row: tuple) -> dict:
    (ext_id, name, website, phone, email, freeform, locality, region,
     postcode, lng, lat, socials, confidence) = row
    social = {}
    for url in socials or []:
        for platform in ("facebook", "instagram", "twitter", "youtube",
                         "tiktok", "whatsapp"):
            if platform in url.lower() and platform not in social:
                social[platform] = url
                break
    return {
        "source_id": "overture",
        "external_id": ext_id,
        "name": name,
        "phone": phone,
        "email": email,
        "website": website,
        "address_line1": freeform,
        "city": locality,
        "province": PROVINCE_BY_CODE.get((region or "").strip().upper()),
        "postal_code": postcode,
        "lat": lat,
        "lng": lng,
        "social": social,
        "raw": {"confidence": confidence, "socials": socials},
    }


def print_summary(candidates: list[dict]) -> None:
    n = max(len(candidates), 1)
    for label, key in (("name", "name"), ("website", "website"),
                       ("phone", "phone"), ("email", "email"),
                       ("city", "city")):
        c = sum(1 for cand in candidates if cand[key])
        print(f"{label + ':':<12} {c} ({c / n:.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", help="Overture release tag (default: latest)")
    parser.add_argument("--write-db", action="store_true",
                        help="upsert into org_candidates")
    args = parser.parse_args()

    release = args.release or latest_release()
    print(f"release: {release}")
    candidates = fetch(release, CANADA_BBOX)

    run_dir = Path("data/runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    out_file = run_dir / "overture_candidates.json"
    out_file.write_text(json.dumps(candidates, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"wrote {out_file}")
    print_summary(candidates)

    if args.write_db:
        if not config.DATABASE_URL:
            raise SystemExit("--write-db requires DATABASE_URL")
        print(f"upserted {upsert(candidates)} candidates")


if __name__ == "__main__":
    main()
