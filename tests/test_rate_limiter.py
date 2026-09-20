"""Rate limiter wait math with fake clock and fake sleep."""
import pytest

from mmh_discovery.crawler.rate_limiter import DomainRateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_first_fetch_never_waits():
    t = FakeTime()
    limiter = DomainRateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    limiter.wait("https://example.com/")
    assert t.slept == []


def test_second_fetch_waits_the_remaining_interval():
    t = FakeTime()
    limiter = DomainRateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    limiter.wait("https://example.com/")
    t.now += 0.4  # 0.4s elapsed since first fetch
    limiter.wait("https://example.com/about")
    assert t.slept == [pytest.approx(0.6)]


def test_no_wait_after_full_interval_elapsed():
    t = FakeTime()
    limiter = DomainRateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    limiter.wait("https://example.com/")
    t.now += 5.0
    limiter.wait("https://example.com/about")
    assert t.slept == []


def test_hosts_are_tracked_independently():
    t = FakeTime()
    limiter = DomainRateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    limiter.wait("https://a.com/")
    limiter.wait("https://b.com/")
    assert t.slept == []
    limiter.wait("https://a.com/x")
    assert t.slept == [1.0]


def test_www_and_bare_host_share_one_bucket():
    # urlparse keeps www as part of the host, so these are separate buckets by
    # design; document the behaviour instead of silently sharing.
    t = FakeTime()
    limiter = DomainRateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    limiter.wait("https://example.com/")
    limiter.wait("https://www.example.com/")
    assert t.slept == []  # different hosts, no wait
