"""KeyPool semantics: rotation on 429, drop on 432, credit budget, error swallow."""
import httpx
import pytest

from mmh_discovery.search.cache import ResponseCache
from mmh_discovery.search.client import AllKeysExhausted, TavilyKeyPool

URL = "https://api.tavily.com/search"


def make_pool(handler, keys=("k1", "k2", "k3", "k4"), **kw):
    kw.setdefault("sleep", lambda s: None)
    return TavilyKeyPool(list(keys), transport=httpx.MockTransport(handler), **kw)


def ok(payload=None):
    return httpx.Response(200, json={"results": payload or [
        {"title": "T", "url": "https://a.ca/contact", "content": "info@a.ca"}]})


def test_success_counts_one_credit_and_normalizes():
    pool = make_pool(lambda req: ok())
    hits = pool.search("q")
    assert hits == [{"title": "T", "url": "https://a.ca/contact", "content": "info@a.ca"}]
    assert pool.credits_used == 1
    pool.close()


def test_429_rotates_keys_then_succeeds():
    seen = []

    def handler(req):
        key = req.headers["Authorization"].removeprefix("Bearer ")
        seen.append(key)
        return httpx.Response(429) if key == "k1" else ok()

    pool = make_pool(handler)
    assert pool.search("q")
    assert "k1" in seen and pool.credits_used == 1
    pool.close()


def test_432_drops_key_and_others_continue():
    def handler(req):
        key = req.headers["Authorization"].removeprefix("Bearer ")
        return httpx.Response(432) if key == "k1" else ok()

    pool = make_pool(handler)
    assert pool.search("q")
    assert pool.dropped == {"k1"}
    pool.close()


def test_all_keys_432_raises():
    pool = make_pool(lambda req: httpx.Response(432), keys=("k1", "k2"))
    with pytest.raises(AllKeysExhausted):
        pool.search("q")
    pool.close()


def test_transport_error_returns_empty_not_raise():
    def handler(req):
        raise httpx.ConnectError("boom")

    pool = make_pool(handler)
    assert pool.search("q") == []
    pool.close()


def test_budget_stops_new_searches():
    calls = []

    def handler(req):
        calls.append(1)
        return ok()

    pool = make_pool(handler, budget=1)
    pool.search("q1")
    assert pool.search("q2") == []
    assert len(calls) == 1  # second search never hit the wire
    pool.close()


def test_empty_keys_rejected():
    with pytest.raises(ValueError):
        TavilyKeyPool([])


# --- response cache (testing without burning credits)

def test_cache_hit_costs_no_credits(tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return ok()

    pool = make_pool(handler, cache=ResponseCache(tmp_path))
    first = pool.search("q")
    second = pool.search("q")
    assert first == second
    assert pool.credits_used == 1 and pool.cache_hits == 1
    assert len(calls) == 1
    pool.close()


def test_cache_persists_across_pools(tmp_path):
    cache = ResponseCache(tmp_path)
    p1 = make_pool(lambda req: ok(), cache=cache)
    p1.search("warm the cache")
    p1.close()
    # second pool: transport would raise if called; cache must answer instead
    def boom(req):
        raise AssertionError("live search should not happen")

    p2 = make_pool(boom, cache=cache)
    assert p2.search("warm the cache")
    assert p2.credits_used == 0
    p2.close()


def test_offline_mode_misses_return_empty(tmp_path):
    def boom(req):
        raise AssertionError("offline must not hit the wire")

    pool = TavilyKeyPool([], sleep=lambda s: None, transport=httpx.MockTransport(boom),
                         cache=ResponseCache(tmp_path), offline=True)
    assert pool.search("not cached") == []
    assert pool.credits_used == 0
    pool.close()
