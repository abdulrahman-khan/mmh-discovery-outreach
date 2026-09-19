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
