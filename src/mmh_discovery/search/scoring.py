"""Hit filtering and quality scoring - masjid-tuned port of tsw agent_1 filter_results.

Dedupe against known URLs, drop blacklisted/aggregator domains, cap hits per
domain, and rank hits likely to carry contact info above generic pages.
"""
from __future__ import annotations

from urllib.parse import urlparse

from mmh_discovery import config

# Shared search blocklist: never-crawl hosts plus enrichment-specific junk.
BLACKLIST_DOMAINS = config.BLOCKED_DOMAINS | config.SEARCH_BLACKLIST_DOMAINS

DOMAIN_CAP = 3  # max hits accepted per domain per run
MIN_SCORE = -2  # below this a hit is noise


def _apex(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def is_blacklisted(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) or d in host
               for d in BLACKLIST_DOMAINS)


def quality_score_hit(*, url: str, title: str, content: str) -> int:
    """Rank likely contact pages above news/wiki/blog noise."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    haystack = f"{title} {content} {path}".lower()
    score = 0
    for term in ("contact", "email", "reach us", "get in touch"):
        if term in path:
            score += 4
    for term in ("masjid", "mosque", "islamic", "islam", "jamat", "musalla"):
        if term in haystack:
            score += 2
    if "@" in haystack:
        score += 3
    for term in ("/blog", "/news", "/event", "/job", "/careers", "/shop", "/donate/"):
        if term in path:
            score -= 3
    if path.endswith((".pdf", ".doc", ".docx")):
        score -= 3
    if parsed.netloc.lower().endswith(".ca"):
        score += 2  # Canada-wide scope: .ca strongly implies a Canadian org
    if "facebook.com" in haystack or "instagram.com" in haystack:
        score -= 2  # social noise in snippets is common; the site itself is preferred
    return score


def filter_hits(
    results: list[dict],
    *,
    seen_urls: set[str],
    domain_counts: dict[str, int],
    domain_cap: int = DOMAIN_CAP,
    min_score: int = MIN_SCORE,
) -> list[dict]:
    """Dedupe + blacklist + score + per-domain cap. Mutates seen_urls and
    domain_counts so the caps accumulate across queries within one run."""
    accepted = []
    for r in results:
        url = (r.get("url") or "").lower()
        if not url or url in seen_urls or is_blacklisted(url):
            continue
        score = quality_score_hit(url=url, title=r.get("title") or "",
                                  content=r.get("content") or "")
        if score < min_score:
            continue
        domain = urlparse(url).netloc.lower()
        if domain_counts.get(domain, 0) >= domain_cap:
            continue
        seen_urls.add(url)
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        accepted.append({**r, "url": url, "quality_score": score})
    return accepted
