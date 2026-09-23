"""Backfill organization provinces and normalize address fields.

Fixes three data problems in one pass:
  1. province normalization - source data mixes 'on'/'ON'; everything is
     uppercased so the client page's province filter cannot split a province.
  2. postal FSA tier - the first postal-code letter maps to a province
     (Canada Post FSA is authoritative). Covers rows with a postal but no
     city. When FSA and city disagree, FSA wins and the conflict is printed.
  3. city tier - curated lookup for the cities present in this dataset.
     Applied only when unambiguous.

Whitespace/invisible chars in city/postal are cleaned on every row.
Ambiguous leftovers (no usable postal, no known city) are reported for
manual entry, never guessed.

Dry-run by default; --apply writes.

Usage: python scripts/backfill_province.py [--apply]
"""
from __future__ import annotations

import argparse
import re

import psycopg

from mmh_discovery import config

VALID = {"ON", "QC", "BC", "AB", "SK", "MB", "NS", "NB", "NL", "PE", "NT", "YT", "NU"}

# Canada Post FSA first letter -> province/territory ('B' is NS, NB is 'E').
FSA = {"A": "NS", "B": "NS", "C": "SK", "E": "NB", "G": "QC", "H": "QC",
       "J": "QC", "K": "ON", "L": "ON", "M": "ON", "N": "ON", "P": "ON",
       "R": "MB", "S": "SK", "T": "AB", "V": "BC", "Y": "NT"}
# 'X' is territorial and needs the digits (X0A/X0C = NU, rest NT) - out of
# scope for this dataset; treated as unknown.

# Curated city -> province for values present in the data (Canadian mosques).
CITY = {
    "mississauga": "ON", "toronto": "ON", "scarborough": "ON", "etobicoke": "ON",
    "thornhill": "ON", "oakville": "ON", "oavkville": "ON",  # observed typo
    "waterloo": "ON", "cambridge": "ON", "london": "ON", "sarnia": "ON",
    "brampton": "ON", "hamilton": "ON", "ottawa": "ON", "cornwall": "ON",
    "gatineau": "QC", "saint-laurent": "QC", "richmond": "BC",
    "vancouver": "BC", "burnaby": "BC", "surrey": "BC", "calgary": "AB",
    "lloydminster": "SK",
}


def clean(s: str | None) -> str:
    # strips U+200E/U+200B junk seen in real rows, collapses whitespace
    s = (s or "").replace("\u200e", "").replace("\u200b", "")
    return re.sub(r"\s+", " ", s).strip()


def province_from_postal(postal: str) -> str | None:
    p = clean(postal).upper()
    prov = FSA.get(p[0]) if p else None
    return prov if prov in VALID else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with psycopg.connect(config.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("select id, name, city, province, postal_code from organizations order by id")
            rows = cur.fetchall()

        updates, backfill, conflicts, unresolved = [], [], [], []
        for oid, name, city, prov, postal in rows:
            city_c, postal_c = clean(city), clean(postal)
            prov_c = clean(prov).upper()
            fp = province_from_postal(postal_c)
            cp = CITY.get(city_c.lower()) if city_c else None

            if fp and cp and fp != cp:
                conflicts.append((name, city_c, postal_c, f"FSA says {fp}, city says {cp}"))

            derived = fp or cp  # FSA wins when they disagree
            new_prov = prov_c if prov_c in VALID else derived

            if derived and prov_c not in VALID:
                backfill.append((oid, name, derived, "postal" if fp else "city"))

            changed = (prov or "") != (new_prov or "") or (city or "") != (city_c or "") \
                or (postal or "") != (postal_c or "")
            if changed:
                updates.append((oid, new_prov, city_c or None, postal_c or None))
            if not new_prov:
                unresolved.append((name, city_c, postal_c))

        print(f"rows to update: {len(updates)}")
        print(f"province backfill ({len(backfill)}):")
        for _, name, p, how in backfill:
            print(f"  [{how:6s}] {p}  {name}")
        if conflicts:
            print(f"conflicts, FSA applied ({len(conflicts)}):")
            for c in conflicts:
                print(f"  {c}")
        print(f"still unresolved ({len(unresolved)}):")
        for name, c, p in unresolved:
            print(f"  {name} | city={c!r} postal={p!r}")

        if args.apply:
            with conn, conn.cursor() as cur:
                cur.executemany(
                    "update organizations set province = %s, city = %s, postal_code = %s where id = %s",
                    [(p, c, z, oid) for oid, p, c, z in updates],
                )
            print(f"applied {len(updates)} updates")


if __name__ == "__main__":
    main()
