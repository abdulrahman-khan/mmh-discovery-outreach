"""Entity resolution: link unresolved org_candidates to organizations.

Match tiers, strongest first (a candidate takes its best tier):
  exact  - candidate website == org website incl. path (normalised: scheme/
           www/slash). A URL with a specific path identifies one institution,
           so no proximity requirement (e.g. ahmadiyya.ca/mosques/<name>).
  domain - same host and exactly one org carries it: shared-platform hosts
           carry many masjids, so require BOTH <=2 km apart AND name
           similarity >= 0.45. Two same-named masjids in different cities
           are two institutions and must never merge.
  geoname- within ~250 m and pg_trgm name similarity >= 0.55
Dry-run by default: prints tier counts and fuzzy-match samples. --apply
stamps resolved_org_id and backfills NULL org fields (phone/email/website/
address/city/province/postal/lat/lng/social) from the linked candidate.

Usage: python scripts/resolve_candidates.py [--apply]
"""
from __future__ import annotations

import argparse

import psycopg

from mmh_discovery import config

NORM_URL = "lower(regexp_replace(%s, '^https?://(www\\.)?', '', 'i'))"
HOST = f"split_part({NORM_URL % '%s'}, '/', 1)"
# Great-circle-ish distance in km, good enough at city scale.
KM = (
    "111.32 * sqrt(power({a}.lat - {b}.lat, 2)"
    " + power(({a}.lng - {b}.lng) * cos(radians({b}.lat)), 2))"
)

# One logical query per tier; each row is (candidate_id, org_id, extra).
TIER_SQL = {
    "exact": f"""
        select c.id, o.id, 1.0
        from org_candidates c
        join organizations o
          on o.website is not null and o.status <> 'merged'
         and {NORM_URL % 'c.website'} = {NORM_URL % 'o.website'}
        where c.resolved_org_id is null and coalesce(c.website, '') <> ''
          -- a full URL match (incl. path) identifies one institution; a bare
          -- host match could be a platform homepage, so require a path or a
          -- platform-subdomain-free site within the same town.
          and (position('/' in {NORM_URL % 'c.website'}) > 0
               or (c.lat is not null and o.lat is not null
                   and {KM.format(a='c', b='o')} <= 2
                   and similarity(lower(c.name), lower(o.name)) >= 0.45))
    """,
    "domain": f"""
        with cand as (
            select id, {HOST % 'website'} as dom, name, lat as lat, lng as lng
            from org_candidates
            where resolved_org_id is null and coalesce(website, '') <> ''
        ),
        org as (
            select id, {HOST % 'website'} as dom, name, lat as lat, lng as lng
            from organizations
            where website is not null and status <> 'merged'
        )
        select c.id, min(o.id::text)::uuid, 0.9
        from cand c join org o using (dom)
        -- same host alone proves nothing: shared platforms carry hundreds of
        -- masjids and two same-named masjids in different cities are two
        -- institutions. Require same-place coordinates AND similar names.
        where c.lat is not null and o.lat is not null
          and {KM.format(a='c', b='o')} <= 2
          and similarity(lower(c.name), lower(o.name)) >= 0.45
        group by c.id
        having count(distinct o.id) = 1
    """,
    "geoname": """
        select c.id, o.id, similarity(lower(c.name), lower(o.name)) as sim
        from org_candidates c
        join organizations o
          on o.status <> 'merged'
         and c.lat between o.lat - 0.0023 and o.lat + 0.0023
         and c.lng between o.lng - 0.0031 and o.lng + 0.0031
        where c.resolved_org_id is null
          and c.lat is not null and o.lat is not null
          and c.name is not null and o.name is not null
          and similarity(lower(c.name), lower(o.name)) >= 0.55
    """,
}


def find_matches(conn) -> dict[str, list[tuple]]:
    """Candidate -> org matches per tier; each candidate appears in one tier only."""
    claimed: set[str] = set()
    result: dict[str, list[tuple]] = {}
    for tier, sql in TIER_SQL.items():
        rows = conn.execute(sql).fetchall()
        # geoname: best sim per candidate
        best: dict[str, tuple] = {}
        for cand_id, org_id, extra in rows:
            if cand_id in claimed:
                continue
            if tier != "geoname" or cand_id not in best or extra > best[cand_id][2]:
                best[cand_id] = (cand_id, org_id, extra)
        kept = sorted(best.values())
        claimed.update(c for c, _, _ in kept)
        result[tier] = kept
    return result


def apply(conn, matches: list[tuple]) -> None:
    pairs = [(org_id, cand_id) for cand_id, org_id, _ in matches]
    with conn.transaction():
        conn.cursor().executemany(
            "update org_candidates set resolved_org_id = %s where id = %s", pairs
        )
        conn.execute(
            """
            update organizations o
               set phone       = coalesce(o.phone, c.phone),
                   email       = coalesce(o.email, c.email),
                   website     = coalesce(o.website, c.website),
                   address_line1 = coalesce(o.address_line1, c.address_line1),
                   city        = coalesce(o.city, c.city),
                   province    = coalesce(o.province, c.province),
                   postal_code = coalesce(o.postal_code, c.postal_code),
                   lat         = coalesce(o.lat, c.lat),
                   lng         = coalesce(o.lng, c.lng),
                   social      = case when o.social = '{}'::jsonb
                                 then c.social else o.social end,
                   updated_at  = now()
            from org_candidates c
            where c.resolved_org_id = o.id
            """
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with psycopg.connect(config.DATABASE_URL) as conn:
        matches = find_matches(conn)
        total_cands = conn.execute(
            "select count(*) from org_candidates where resolved_org_id is null"
        ).fetchone()[0]
        for tier, rows in matches.items():
            print(f"{tier:<8} {len(rows)}")
            if tier == "geoname":
                for cand_id, org_id, sim in rows[:10]:
                    c, o = conn.execute(
                        "select (select name from org_candidates where id = %s),"
                        " (select name from organizations where id = %s)",
                        (cand_id, org_id),
                    ).fetchone()
                    print(f"    sim={sim:.2f}  {c!r} -> {o!r}")
        print(f"unresolved candidates before: {total_cands}")

        if args.apply and any(matches.values()):
            flat = [m for rows in matches.values() for m in rows]
            apply(conn, flat)
            left = conn.execute(
                "select count(*) from org_candidates where resolved_org_id is null"
            ).fetchone()[0]
            print(f"applied {len(flat)} links; unresolved now: {left}")
        elif not args.apply:
            print("dry run (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
