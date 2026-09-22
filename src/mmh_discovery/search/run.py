"""Search-pipeline worker: Tavily second chance before the manual queue.

Targets (per DEVNOTES/SEARCH-PIPELINE-SPEC.md):
  1. manual_entry_queue rows still missing email/phone/province (D-003 second
     chance: blocked sites are searched, never fetched);
  2. organizations with no province (search the name, derive geo from snippets).

Flow per target: query templates -> KeyPool search -> filter/score -> regex
extract -> vet -> enrichment_proposals rows. `--apply` writes verified rows
only, never over an existing non-null value. Dry-run by default.

Usage: python -m mmh_discovery.search.run [--limit N] [--dry-run] [--apply]
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from mmh_discovery import config
from mmh_discovery.search import geo
from mmh_discovery.search.cache import ResponseCache, query_key
from mmh_discovery.search.client import AllKeysExhausted, TavilyKeyPool
from mmh_discovery.search.extract import extract_fields
from mmh_discovery.search.queries import SearchTarget, build_query_slots
from mmh_discovery.search.scoring import filter_hits, is_blacklisted
from mmh_discovery.search.vetting import (
    VERIFIED,
    on_org_page,
    org_apex,
    vet,
    vet_city_prov,
)

log = logging.getLogger(__name__)

METHOD = "search:tavily-v1"


@dataclass
class Proposal:
    target: SearchTarget
    field: str
    value: str
    source_url: str
    evidence: str
    vetting: str
    vet_rule: str


def load_targets(conn: psycopg.Connection, limit: int) -> list[SearchTarget]:
    """Queue rows missing contact data first, then province-less orgs."""
    targets: list[SearchTarget] = []
    rows = conn.execute("""
        select domain, url, org_id, name, city, province,
               coalesce(org_email, candidate_email) is not null      as has_email,
               coalesce(org_phone, candidate_phone) is not null      as has_phone,
               coalesce(province, '') <> ''                          as has_province
        from manual_entry_queue
        where coalesce(org_email, candidate_email) is null
           or coalesce(org_phone, candidate_phone) is null
           or coalesce(province, '') = ''
        order by domain
        """).fetchall()
    for domain, url, org_id, name, city, _province, has_email, has_phone, has_prov in rows:
        missing = tuple(f for f, has in (("email", has_email), ("phone", has_phone),
                                         ("province", has_prov)) if not has)
        targets.append(SearchTarget(
            org_id=str(org_id) if org_id else None, candidate_id=None,
            domain=domain, name=(name or domain or "").strip(), website=url,
            city=city, missing=missing))
    if len(targets) < limit:
        rows = conn.execute("""
            select id, name, website, city from organizations
            where province is null and status <> 'merged'
            order by created_at
            limit %s
            """, (limit - len(targets),)).fetchall()
        for oid, name, website, city in rows:
            targets.append(SearchTarget(
                org_id=str(oid), candidate_id=None, domain=None, name=name,
                website=website, city=city, missing=("province", "city")))
    return targets[:limit]


def proposal_values(target: SearchTarget, hit: dict, fields: dict) -> list[Proposal]:
    """Turn one hit's extracted fields into vetted proposals for this target."""
    ev = (hit.get("content") or hit.get("title") or "")[:300]
    out: list[Proposal] = []

    def add(field: str, value: str, vetting: str, rule: str) -> None:
        out.append(Proposal(target, field, value, hit["url"], ev, vetting, rule))

    if "email" in target.missing:
        for email in fields["emails"][:2]:
            v, rule = vet("email", email, hit["url"],
                          website=target.website, domain=target.domain)
            add("email", email, v, rule)
    if "phone" in target.missing and fields["phone"]:
        v, rule = vet("phone", fields["phone"], hit["url"],
                      website=target.website, domain=target.domain)
        add("phone", fields["phone"], v, rule)
    if "province" in target.missing:
        if not is_blacklisted(hit["url"]) and on_org_page(hit["url"],
                                                          org_apex(target.website,
                                                                   target.domain)):
            prov = geo.province_from_fsa(fields["fsa"])
            if prov:
                add("province", prov, VERIFIED, "province_fsa_own_page")
                add("postal_code", fields["fsa"], VERIFIED, "fsa_own_page")
        if fields["city"] and fields["province"]:
            v, rule = vet_city_prov(fields["city"], fields["province"],
                                    city_ok=geo.CITY_PROVINCE)
            add("city", fields["city"], v, rule)
            if v == VERIFIED:
                add("province", fields["province"], v, rule)
    return out


def load_ledger(conn: psycopg.Connection, freshness_days: int) -> set[str]:
    """Query hashes searched within the freshness window (cross-run).
    A slot in the ledger with no local cache hit is skipped: novelty is a
    property of the ledger, not of the query generator."""
    rows = conn.execute(
        "select query_hash from search_query_ledger "
        "where searched_at > now() - (%s || ' days')::interval",
        (freshness_days,)).fetchall()
    return {r[0] for r in rows}


def record_ledger(conn: psycopg.Connection, run_id: str,
                  entries: list[tuple[str, str, str, str | None, int]]) -> None:
    for qkey, query, template, domain, n_results in entries:
        conn.execute("""
            insert into search_query_ledger
              (query_hash, query, target_domain, template, results_count, run_id)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (query_hash) do update set
              searched_at = now(), run_id = excluded.run_id
            """, (qkey, query, domain, template, n_results, run_id))


def run_search(pool: TavilyKeyPool, target: SearchTarget,
               seen_urls: set[str], domain_counts: dict[str, int],
               ledger: frozenset[str] = frozenset(),
               ledger_entries: list | None = None,
               freshness_days: int = 0) -> list[Proposal]:
    proposals: list[Proposal] = []
    found: set[str] = set()
    for template, query in build_query_slots(target):
        if found >= set(target.missing) or pool.budget_exhausted:
            break
        qkey = query_key(query)
        if freshness_days and qkey in ledger and pool.cache_get(query) is None:
            log.debug("ledger skip (%s): %s", template, query)
            continue
        hits = filter_hits(pool.search(query), seen_urls=seen_urls,
                           domain_counts=domain_counts)
        if ledger_entries is not None:
            ledger_entries.append((qkey, query, template, target.domain, len(hits)))
        for hit in sorted(hits, key=lambda h: -h["quality_score"]):
            fields = extract_fields(hit)
            for prop in proposal_values(target, hit, fields):
                proposals.append(prop)
                found.add(prop.field if prop.field != "postal_code" else "province")
    return proposals


def store_proposals(conn: psycopg.Connection, run_id: str,
                    proposals: list[Proposal]) -> int:
    n = 0
    for p in proposals:
        conn.execute("""
            insert into enrichment_proposals
              (run_id, org_id, candidate_id, domain, field, proposed_value,
               source_url, evidence, vetting, vet_rule)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (org_id, candidate_id, field, proposed_value)
              do update set run_id = excluded.run_id, source_url = excluded.source_url,
                            evidence = excluded.evidence, vetting = excluded.vetting,
                            vet_rule = excluded.vet_rule
            """, (run_id, p.target.org_id, p.target.candidate_id, p.target.domain,
                  p.field, p.value, p.source_url, p.evidence, p.vetting, p.vet_rule))
        n += 1
    return n


def apply_verified(conn: psycopg.Connection) -> int:
    """Write verified proposals: candidate row when one exists, else the org.
    Never overwrites an existing non-null value (proposals fill gaps only).
    city+province verified under the same rule are written together."""
    rows = conn.execute("""
        select id, org_id, candidate_id, field, proposed_value, source_url
        from enrichment_proposals
        where vetting = 'verified' and status = 'open'
        order by created_at
        """).fetchall()
    applied = 0
    for pid, org_id, candidate_id, field, value, _source_url in rows:
        table = "org_candidates" if candidate_id else "organizations"
        key = "id"
        where_id = candidate_id if candidate_id else org_id
        if where_id is None:
            continue
        if field == "city":  # paired with province under city_table_agrees
            prov = conn.execute("""
                select proposed_value from enrichment_proposals
                where field = 'province' and vetting = 'verified' and status = 'open'
                  and org_id is not distinct from %s
                  and vet_rule = 'city_table_agrees' limit 1
                """, (org_id,)).fetchone()
            extra = ", province = coalesce(province, %s)" if prov else ""
            params = [value] + ([prov[0]] if prov else [])
            sql = (f"update {table} set city = coalesce(city, %s){extra} "
                   f"where {key} = %s returning city, province")
            cur = conn.execute(sql, (*params, where_id))
            if prov:
                conn.execute("update enrichment_proposals set status = 'applied', "
                             "applied_at = now() where field = 'province' "
                             "and vetting = 'verified' and status = 'open' "
                             "and org_id is not distinct from %s "
                             "and vet_rule = 'city_table_agrees'", (org_id,))
        elif field == "province":
            cur = conn.execute(
                f"update {table} set province = coalesce(province, %s) "
                f"where {key} = %s returning province", (value, where_id))
        elif field == "postal_code":
            cur = conn.execute(
                f"update {table} set postal_code = coalesce(postal_code, %s) "
                f"where {key} = %s returning postal_code", (value, where_id))
        else:  # email / phone / website on candidate level
            cur = conn.execute(
                f"update {table} set {field} = coalesce({field}, %s) "
                f"where {key} = %s returning {field}", (value, where_id))
        if cur.fetchone() is not None:
            conn.execute("update enrichment_proposals set status = 'applied', "
                         "applied_at = now() where id = %s", (pid,))
            applied += 1
    return applied


def run(run_id: str, limit: int, dry_run: bool, apply: bool,
        offline: bool = False, freshness_days: int | None = None) -> int:
    freshness = config.SEARCH_QUERY_FRESHNESS_DAYS if freshness_days is None \
        else freshness_days
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL missing (set in .env)")
    if not config.TAVILY_API_KEYS and not offline:
        raise SystemExit("TAVILY_API_KEYS missing (set in .env)")
    pool = TavilyKeyPool(config.TAVILY_API_KEYS,
                         cache=ResponseCache(Path(config.DATA_DIR) / "search_cache"),
                         offline=offline)
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    ledger_entries: list = []
    n_props = n_verified = 0
    try:
        with psycopg.connect(config.DATABASE_URL) as conn:
            targets = load_targets(conn, limit)
            ledger = frozenset(load_ledger(conn, freshness)) if freshness else frozenset()
        log.info("targets: %d | credit budget: %d | ledger slots fresh: %d "
                 "(window %dd)", len(targets), pool.budget, len(ledger), freshness)
        all_props: list[Proposal] = []
        for i, target in enumerate(targets, 1):
            try:
                props = run_search(pool, target, seen_urls, domain_counts,
                                   ledger=ledger, ledger_entries=ledger_entries,
                                   freshness_days=freshness)
            except AllKeysExhausted:
                log.error("all Tavily keys out of credits after %d searches; "
                          "storing %d proposals collected so far",
                          pool.credits_used, len(all_props))
                break
            all_props.extend(props)
            n_props += len(props)
            n_verified += sum(1 for p in props if p.vetting == VERIFIED)
            label = target.domain or target.name
            found = " ".join(f"{p.field}:{p.vetting[0]}={p.value}" for p in props[:4])
            log.info("[%d/%d] %s (missing %s): %s", i, len(targets), label,
                     ",".join(target.missing), found or "nothing")
        if not dry_run and all_props:
            with psycopg.connect(config.DATABASE_URL) as conn:
                store_proposals(conn, run_id, all_props)
                conn.commit()
        if not dry_run and ledger_entries:
            with psycopg.connect(config.DATABASE_URL) as conn:
                record_ledger(conn, run_id, ledger_entries)
                conn.commit()
        if apply and not dry_run:
            with psycopg.connect(config.DATABASE_URL) as conn:
                n = apply_verified(conn)
                conn.commit()
            log.info("applied %d verified proposals", n)
        log.info("run %s: searches=%d/%d credits, cache_hits=%d, proposals=%d "
                 "verified=%d dry_run=%s",
                 run_id, pool.credits_used, pool.budget, pool.cache_hits,
                 n_props, n_verified, dry_run)
    finally:
        pool.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=10, help="max targets")
    ap.add_argument("--dry-run", action="store_true", help="search but write nothing")
    ap.add_argument("--apply", action="store_true",
                    help="write verified proposals to org_candidates/organizations")
    ap.add_argument("--offline", action="store_true",
                    help="answer searches only from the response cache (zero credits)")
    ap.add_argument("--freshness-days", type=int, default=None,
                    help="ledger window: skip (target x template) slots searched "
                         "within N days across all runs (0 = ignore ledger)")
    args = ap.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return run(run_id, args.limit, args.dry_run, args.apply, args.offline,
               args.freshness_days)


if __name__ == "__main__":
    raise SystemExit(main())
