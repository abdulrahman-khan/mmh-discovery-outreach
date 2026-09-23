"""Seed crawl_jobs from org_candidates that carry a website. Idempotent.

One job per website URL (reason='discover'); unique (url, reason) keeps
re-runs cheap. Blocklisted hosts are skipped at seed time. Existing jobs are
left untouched unless they are 'failed' and their cooldown has passed, in
which case they are re-queued.

Usage: python scripts/seed_crawl_jobs.py [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse

import psycopg

from mmh_discovery import config
from mmh_discovery.core.naming import domain_from_url
from mmh_discovery.crawler.bfs import canonicalise_seed, is_blocked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=0, help="max candidate websites to seed (0 = all)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL missing (set in .env)")

    sql = """
        select distinct on (lower(regexp_replace(website, '^https?://(www\\.)?', '', 'i')))
               website
        from org_candidates
        where website is not null and website <> ''
        order by lower(regexp_replace(website, '^https?://(www\\.)?', '', 'i')), created_at
    """
    if args.limit > 0:
        sql += " limit %s"

    inserted = skipped_blocked = 0
    with psycopg.connect(config.DATABASE_URL, autocommit=not args.dry_run) as conn:
        rows = conn.execute(sql, (args.limit,) if args.limit > 0 else ()).fetchall()
        for (website,) in rows:
            url = canonicalise_seed(website)
            if is_blocked(url):
                skipped_blocked += 1
                continue
            domain = domain_from_url(url)
            if args.dry_run:
                print(f"would queue: {url}")
                inserted += 1
                continue
            conn.execute(
                """
                insert into crawl_jobs (url, domain, reason, status)
                values (%s, %s, 'discover', 'queued')
                on conflict (url, reason) do update
                set status = 'queued', next_attempt_at = null
                where crawl_jobs.status = 'failed'
                  and (crawl_jobs.fail_category is null or crawl_jobs.fail_category <> 'blocked')
                """,
                (url, domain),
            )
            inserted += 1

    print(f"seeded {inserted} urls ({skipped_blocked} blocklisted skipped)"
          + (" [dry-run]" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
