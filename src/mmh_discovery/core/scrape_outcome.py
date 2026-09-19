"""Scrape failure classification - single source of truth for outcome categories."""
from __future__ import annotations

RETRYABLE = "retryable"
BLOCKED = "blocked"
THIN = "thin"
PERMANENT = "permanent"
OK = "ok"

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def classify_scrape_failure(reason: str | None) -> str:
    """Map a recorded fail_reason string to a failure category."""
    if not reason:
        return PERMANENT
    r = reason.lower()

    if r.startswith("error:") or "timeout" in r or "connection" in r:
        return RETRYABLE

    if r.startswith("status "):
        try:
            code = int(r.split()[1])
        except (IndexError, ValueError):
            return PERMANENT
        if code in RETRYABLE_STATUSES:
            return RETRYABLE
        if code == 403:
            return BLOCKED
        return PERMANENT

    if r.startswith("blocked"):
        return BLOCKED

    if r.startswith("content too short"):
        return THIN

    return PERMANENT


def is_retryable(reason: str | None) -> bool:
    return classify_scrape_failure(reason) == RETRYABLE
