"""One-shot pipeline worker: claim queued crawl_jobs -> BFS crawl (serial,
rate-limited) -> LLM extract + persist (thread pool, LLM_MAX_CONCURRENCY).

Usage: python -m mmh_discovery.pipeline.run_once [--limit N] [--dry-run]

Crawls run serially on the main thread (one polite socket, shared per-domain
rate limiter); each finished crawl is handed to the executor for the LLM call
and DB write. Threads never share a psycopg connection: each gets its own.
"""
from __future__ import annotations

import argparse
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import psycopg
import truststore

from mmh_discovery import config
from mmh_discovery.core.scrape_outcome import RETRYABLE, classify_scrape_failure
from mmh_discovery.crawler.crawler import Crawler, CrawlOutcome
from mmh_discovery.crawler.fetcher import Fetcher
from mmh_discovery.crawler.rate_limiter import DomainRateLimiter
from mmh_discovery.crawler.robots import RobotsPolicy
from mmh_discovery.extractor.extract import ExtractionError, ExtractionStats, extract_domain
from mmh_discovery.extractor.llm_client import LLMClient
from mmh_discovery.extractor.metrics import RunMetrics
from mmh_discovery.extractor.writer import persist_extraction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Job:
    id: str
    url: str
    domain: str
    org_id: str | None


def claim_jobs(conn: psycopg.Connection, limit: int, run_id: str, dry_run: bool) -> list[Job]:
    """Atomically move up to `limit` queued jobs to running and return them.
    dry_run only reads: no state mutation in claim or finish."""
    if dry_run:
        rows = conn.execute(
            """
            select id, url, coalesce(domain, ''), org_id
            from crawl_jobs
            where status = 'queued'
              and (next_attempt_at is null or next_attempt_at <= now())
            order by queued_at
            limit %s
            """,
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            update crawl_jobs
            set status = 'running', started_at = now(), attempts = attempts + 1, run_id = %s
            where id in (
                select id from crawl_jobs
                where status = 'queued'
                  and (next_attempt_at is null or next_attempt_at <= now())
                order by queued_at
                limit %s
                for update skip locked
            )
            returning id, url, coalesce(domain, ''), org_id
            """,
            (run_id, limit),
        ).fetchall()
    return [Job(str(r[0]), r[1], r[2], str(r[3]) if r[3] else None) for r in rows]


def finish_job(conn: psycopg.Connection, job: Job, status: str, fail_reason: str | None) -> None:
    category = classify_scrape_failure(fail_reason) if fail_reason else None
    if status == "failed" and category == RETRYABLE:
        # Transient failures (timeouts, 429/5xx, DNS) re-enter the queue after
        # the cooldown; anything else stays terminal for this job.
        conn.execute(
            """
            update crawl_jobs
            set status = 'queued', finished_at = now(), fail_category = %s, fail_reason = %s,
                next_attempt_at = now() + (%s || ' days')::interval
            where id = %s
            """,
            (category, fail_reason, config.RETRY_COOLDOWN_DAYS, job.id),
        )
        return
    conn.execute(
        """
        update crawl_jobs
        set status = %s, finished_at = now(), fail_category = %s, fail_reason = %s
        where id = %s
        """,
        (status, category, fail_reason, job.id),
    )


def resolve_org(conn: psycopg.Connection, job: Job) -> str | None:
    """org_id from the job, else the candidate whose website is EXACTLY this
    job URL (shared-platform hosts carry many masjids under one domain, so a
    domain-prefix match would collapse them all into one org). Reuse the
    candidate's resolved org, an existing org with the same website, or create
    one from the candidate. One-candidate-one-org stub until real entity
    resolution lands."""
    if job.org_id:
        return job.org_id
    # Compare scheme/www/trailing-slash-insensitive URL equality.
    norm = "lower(rtrim(regexp_replace(coalesce({col}, ''), '^https?://(www\\.)?', ''), '/'))"
    row = conn.execute(
        f"""
        select id, resolved_org_id, name, website, city, province, lat, lng
        from org_candidates
        where {norm.format(col="website")} = {norm.format(col="%s")}
        order by resolved_org_id nulls last, created_at
        limit 1
        """,
        (job.url,),
    ).fetchone()
    if row is None:
        return None
    candidate_id, resolved, name, website, city, province, lat, lng = row
    if resolved:
        return str(resolved)
    # Never create a second org for a website we already have.
    existing = conn.execute(
        f"select id from organizations where {norm.format(col='website')} = %s limit 1",
        (job.url,),
    ).fetchone()
    if existing:
        org_id = existing[0]
    else:
        org_id = conn.execute(
            """
            insert into organizations (name, website, city, province, lat, lng)
            values (%s, %s, %s, %s, %s, %s) returning id
            """,
            (name or job.domain, website, city, province, lat, lng),
        ).fetchone()[0]
    # Stamp only the matched candidate row (a domain-wide update mis-resolves
    # every sibling candidate on shared platforms).
    conn.execute(
        "update org_candidates set resolved_org_id = %s where id = %s",
        (org_id, candidate_id),
    )
    return str(org_id)


def process_job(
    dsn: str,
    llm: LLMClient,
    job: Job,
    outcome: CrawlOutcome,
    metrics: RunMetrics,
    dry_run: bool,
    run_id: str,
) -> None:
    """Runs on a worker thread: extract + persist for one domain."""
    stats = ExtractionStats()
    pages = [(p.final_url, p.status, p.html) for p in outcome.pages]
    extract_pages = [(p.final_url, p.html) for p in outcome.pages]
    with psycopg.connect(dsn) as conn:
        try:
            org_id = resolve_org(conn, job)
            if org_id is None:
                raise ExtractionError("no organization resolved for domain")
            result, stats = extract_domain(llm, extract_pages)
            if dry_run:
                counts = {
                    "email": len(result.emails),
                    "phone": len(result.phones),
                    "social": len(result.socials),
                    "contact_form": len(result.contact_forms),
                    "raw_context": len(result.raw_context),
                }
            else:
                counts = persist_extraction(conn, org_id, result, run_id, pages)
                conn.commit()
            metrics.record_domain(job.domain, org_id, stats, counts)
            if not dry_run:
                finish_job(conn, job, "done", None)
            log.info("done %s: %s", job.domain, counts)
        except Exception as exc:  # per-job boundary: one bad domain must not kill the run
            conn.rollback()
            metrics.record_domain(job.domain, job.org_id, stats, error=str(exc)[:500])
            if not dry_run:
                finish_job(conn, job, "failed", str(exc)[:500])
            log.exception("job failed for %s", job.domain)


def run(run_id: str, limit: int, dry_run: bool) -> int:
    # Verify TLS against the OS trust store, not certifi: many small org sites
    # ship incomplete chains that browsers tolerate (Schannel auto-fetches
    # missing intermediates). Must run before any HTTPS connection.
    truststore.inject_into_ssl()

    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL missing (set in .env)")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    metrics = RunMetrics(run_id, config.DATA_DIR)
    llm = LLMClient()
    limiter = DomainRateLimiter(config.PER_DOMAIN_MIN_INTERVAL_SECONDS)
    crawl_failures: list[tuple[Job, str]] = []

    with psycopg.connect(config.DATABASE_URL) as conn:
        jobs = claim_jobs(conn, limit, run_id, dry_run)
        conn.commit()
    if not jobs:
        log.info("no queued jobs")
        return 0

    with httpx.Client() as http, psycopg.connect(config.DATABASE_URL) as conn:
        robots = RobotsPolicy(http, allowlist=config.ROBOTS_ALLOWLIST)
        crawler = Crawler(Fetcher(http, robots, limiter))
        with ThreadPoolExecutor(max_workers=config.LLM_MAX_CONCURRENCY) as pool:
            futures: list[Future] = []
            for job in jobs:
                log.info("crawling %s (%s)", job.url, job.domain)
                outcome = crawler.crawl(job.url)
                if not outcome.ok:
                    reason = (
                        outcome.failures[0].fail_reason if outcome.failures else "no pages fetched"
                    )
                    crawl_failures.append((job, reason))
                    continue
                metrics.record_pages(len(outcome.pages))
                futures.append(
                    pool.submit(
                        process_job, config.DATABASE_URL, llm, job, outcome,
                        metrics, dry_run, run_id,
                    )
                )
            for f in futures:
                f.result()  # surface unexpected thread bugs

        # Crawl-level failures: jobs never reached the extractor.
        for job, reason in crawl_failures:
            metrics.errors.append(f"{job.domain}: crawl failed: {reason}")
            metrics.rejected += 1
            if not dry_run:
                finish_job(conn, job, "failed", f"crawl failed: {reason}")
        conn.commit()

        if not dry_run:
            metrics.finalize(conn)
            conn.commit()

    llm.close()
    log.info(
        "run %s: pages=%d orgs_updated=%d rejected=%d tokens=%d/%d metrics=%s",
        run_id, metrics.pages_seen, metrics.orgs_updated, metrics.rejected,
        metrics.prompt_tokens, metrics.completion_tokens, metrics.path,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="max jobs to claim")
    parser.add_argument("--dry-run", action="store_true", help="extract but skip all DB writes")
    args = parser.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return run(run_id, args.limit, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
