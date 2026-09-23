"""BFS crawler for one website seed.

FIFO breadth-first up to CRAWLER_MAX_PAGES_PER_DOMAIN pages. Never early-stops
while more in-scope pages remain. Shared-platform seeds fetch exactly one page.
No page is fetched twice; out-of-scope, blocklisted, and non-HTML URLs are
dropped at enqueue time.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

from mmh_discovery import config
from mmh_discovery.crawler.bfs import (
    canonicalise_seed,
    extract_links,
    is_blocked,
    is_crawlable,
    is_shared_platform,
    same_scope,
)
from mmh_discovery.crawler.fetcher import Fetcher, FetchResult

log = logging.getLogger(__name__)


@dataclass
class CrawlOutcome:
    seed_url: str
    pages: list[FetchResult] = field(default_factory=list)  # ok fetches, in crawl order
    failures: list[FetchResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.pages)


class Crawler:
    def __init__(self, fetcher: Fetcher, max_pages: int | None = None) -> None:
        self._fetcher = fetcher
        self._max_pages = max_pages or config.CRAWLER_MAX_PAGES_PER_DOMAIN

    def crawl(self, seed_url: str) -> CrawlOutcome:
        seed = canonicalise_seed(seed_url)
        outcome = CrawlOutcome(seed_url=seed)
        if is_blocked(seed):
            log.info("seed blocklisted, skipping: %s", seed)
            return outcome

        shared = is_shared_platform(seed)
        queue: deque[str] = deque([seed])
        enqueued = {seed}

        while queue and len(outcome.pages) < self._max_pages:
            url = queue.popleft()
            result = self._fetcher.fetch(url)
            if not result.ok:
                outcome.failures.append(result)
                continue
            outcome.pages.append(result)
            if shared:
                break  # shared platform: the seed page only, no BFS
            for link in extract_links(result.final_url, result.html):
                if link in enqueued:
                    continue
                if is_blocked(link) or not is_crawlable(link) or not same_scope(seed, link):
                    continue
                enqueued.add(link)
                queue.append(link)

        return outcome
