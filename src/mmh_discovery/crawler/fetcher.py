"""One polite, guarded HTTP fetch.

Order of checks: SSRF (url_guard) -> robots -> rate limit -> request.
Retries transient failures with exponential backoff (tenacity). Outcomes are
classified through core.scrape_outcome so the rest of the pipeline speaks one
failure taxonomy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from tenacity import Retrying, stop_after_attempt, wait_exponential

from mmh_discovery import config
from mmh_discovery.core import scrape_outcome
from mmh_discovery.core.url_guard import is_safe_public_url
from mmh_discovery.crawler.rate_limiter import DomainRateLimiter
from mmh_discovery.crawler.robots import RobotsPolicy

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int | None
    ok: bool
    html: str
    fail_reason: str | None


class Fetcher:
    def __init__(
        self,
        client: httpx.Client,
        robots: RobotsPolicy,
        rate_limiter: DomainRateLimiter,
    ) -> None:
        self._client = client
        self._robots = robots
        self._limiter = rate_limiter

    def _request(self, url: str) -> httpx.Response:
        resp = self._client.get(
            url,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": config.USER_AGENT},
        )
        if resp.status_code in scrape_outcome.RETRYABLE_STATUSES:
            raise _RetryableStatus(resp)
        return resp

    def fetch(self, url: str) -> FetchResult:
        ok, reason = is_safe_public_url(url)
        if not ok:
            return FetchResult(url, url, None, False, "", f"blocked by url_guard: {reason}")
        if not self._robots.can_fetch(url):
            return FetchResult(url, url, None, False, "", "blocked by robots.txt")

        self._limiter.wait(url)
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(config.MAX_RETRIES + 1),
                wait=wait_exponential(multiplier=config.RETRY_BACKOFF_BASE, min=1),
                retry=retry_if_retryable,
                reraise=True,
            ):
                with attempt:
                    resp = self._request(url)
        except _RetryableStatus as exc:
            resp = exc.response
        except httpx.HTTPError as exc:
            return FetchResult(url, url, None, False, "", f"error: {type(exc).__name__}: {exc}")

        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            return FetchResult(url, str(resp.url), resp.status_code, False, "",
                               f"status {resp.status_code}")
        if "html" not in content_type.lower():
            return FetchResult(url, str(resp.url), resp.status_code, False, "",
                               f"not html: {content_type or '(no content-type)'}")
        html = resp.text
        if len(html.encode("utf-8", errors="ignore")) < config.MIN_CONTENT_BYTES:
            return FetchResult(url, str(resp.url), resp.status_code, False, "",
                               f"content too short: {len(html)} bytes")
        return FetchResult(url, str(resp.url), resp.status_code, True, html, None)


class _RetryableStatus(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"status {response.status_code}")
        self.response = response


def retry_if_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (_RetryableStatus, httpx.TransportError))
