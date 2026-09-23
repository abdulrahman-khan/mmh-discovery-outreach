"""robots.txt policy with per-host cache.

Failures degrade to "allow": an unreachable or malformed robots.txt must not
become an accidental crawl ban. Hosts on the allowlist skip enforcement
entirely (manual review required before adding a host).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from mmh_discovery import config

log = logging.getLogger(__name__)


def _host_matches(host: str, entry: str) -> bool:
    """True if host is the entry itself or a subdomain of it."""
    return host == entry or host.endswith("." + entry)


class RobotsPolicy:
    def __init__(
        self,
        client: httpx.Client,
        user_agent: str = config.USER_AGENT,
        allowlist: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        self._allowlist = {h.lower() for h in allowlist}
        self._cache: dict[str, RobotFileParser | None] = {}

    def _parser_for(self, url: str) -> RobotFileParser | None:
        """Fetch and cache /robots.txt for the URL's origin. None = unavailable."""
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in self._cache:
            return self._cache[origin]
        parser: RobotFileParser | None = None
        try:
            resp = self._client.get(
                urljoin(origin + "/", "robots.txt"),
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
            if resp.status_code < 400:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
        except httpx.HTTPError as exc:
            log.debug("robots.txt unavailable for %s: %s", origin, exc)
        self._cache[origin] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if host and any(_host_matches(host, entry) for entry in self._allowlist):
            return True
        parser = self._parser_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self._user_agent, url)
