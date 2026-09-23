"""Scrape failure classification - single source of truth for outcome categories.

Patterns are matched anywhere in the reason because callers record composed
strings like "crawl failed: status 503".
"""
from __future__ import annotations

import re

RETRYABLE = "retryable"
BLOCKED = "blocked"
THIN = "thin"
PERMANENT = "permanent"
OK = "ok"

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_STATUS_RE = re.compile(r"status (\d+)")


def classify_scrape_failure(reason: str | None) -> str:
    """Map a recorded fail_reason string to a failure category."""
    if not reason:
        return PERMANENT
    r = reason.lower()

    if "blocked by robots" in r or "url_guard" in r:
        # Site policy / SSRF guard: the crawler must not retry these.
        return BLOCKED

    if _STATUS_RE.search(r):
        code = int(_STATUS_RE.search(r).group(1))
        if code == 403:
            # WAF/anti-bot: not our crawler's fault; route to manual entry (D-003).
            return BLOCKED
        return RETRYABLE if code in RETRYABLE_STATUSES else PERMANENT

    if "error:" in r or "timeout" in r or "connection" in r or "dns" in r:
        return RETRYABLE

    if r.startswith("blocked"):
        return BLOCKED

    if "content too short" in r:
        return THIN

    return PERMANENT


def is_retryable(reason: str | None) -> bool:
    return classify_scrape_failure(reason) == RETRYABLE
