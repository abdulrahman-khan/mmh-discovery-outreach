"""Failure classification: bare reason strings and the composed strings the pipeline records."""
from mmh_discovery.core.scrape_outcome import (
    BLOCKED,
    PERMANENT,
    RETRYABLE,
    THIN,
    classify_scrape_failure,
)


def test_transient_statuses_are_retryable():
    for reason in ("status 429", "status 500", "status 502", "status 503", "status 504"):
        assert classify_scrape_failure(reason) == RETRYABLE, reason


def test_permanent_statuses():
    for reason in ("status 404", "status 410", "status 451"):
        assert classify_scrape_failure(reason) == PERMANENT, reason


def test_blocked():
    assert classify_scrape_failure("blocked 403") == BLOCKED
    assert classify_scrape_failure("blocked unsafe redirect: loopback") == BLOCKED


def test_connection_errors_retryable():
    assert classify_scrape_failure("error: connection reset") == RETRYABLE
    assert classify_scrape_failure("read timeout") == RETRYABLE


def test_thin():
    assert classify_scrape_failure("content too short (120 chars)") == THIN


def test_none_is_permanent():
    assert classify_scrape_failure(None) == PERMANENT


# --- composed reasons (what run_once actually records) ---

def test_composed_status_reasons():
    assert classify_scrape_failure("crawl failed: status 503") == RETRYABLE
    assert classify_scrape_failure("crawl failed: status 404") == PERMANENT
    assert classify_scrape_failure("crawl failed: status 403") == BLOCKED


def test_policy_blocks_are_blocked_not_retryable():
    assert classify_scrape_failure("crawl failed: blocked by robots.txt") == BLOCKED
    assert classify_scrape_failure(
        "crawl failed: blocked by url_guard: dns resolution failed") == BLOCKED


def test_transient_errors_and_dns():
    assert classify_scrape_failure(
        "crawl failed: error: ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] ...") == RETRYABLE
    assert classify_scrape_failure("crawl failed: error: ConnectTimeout: ...") == RETRYABLE


def test_composed_thin():
    assert classify_scrape_failure("crawl failed: content too short: 98 bytes") == THIN
