"""Per-domain minimum interval between fetches.

clock/sleep are injectable so tests can verify wait math without real time.
wait() accepts a full URL or a bare host.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlparse


class DomainRateLimiter:
    def __init__(
        self,
        min_interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = float(min_interval_seconds)
        self._clock = clock
        self._sleep = sleep
        self._last_fetch: dict[str, float] = {}

    @staticmethod
    def _host_of(url_or_host: str) -> str:
        host = urlparse(url_or_host).hostname
        return (host or url_or_host).lower()

    def wait(self, url_or_host: str) -> None:
        """Block until min_interval_seconds have passed since the last fetch
        of this host, then stamp now as the fetch time."""
        host = self._host_of(url_or_host)
        now = self._clock()
        last = self._last_fetch.get(host)
        if last is not None:
            remaining = self._interval - (now - last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_fetch[host] = now
