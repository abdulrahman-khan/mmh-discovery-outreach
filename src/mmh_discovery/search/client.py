"""Tavily search client with a rotating key pool and a per-run credit budget.

Promoted from scripts/enrich_queue.py (working KeyPool semantics):
429 -> sleep and rotate to the next key; 432 -> drop the key for the run;
all keys dropped -> AllKeysExhausted. Every successful call counts one credit
(Tavily basic search is 1 credit/call); the budget stops new searches, it does
not abort an in-flight one. httpx with an injectable transport so tests never
burn real credits.
"""
from __future__ import annotations

import itertools
import time
from typing import Protocol

import httpx

from mmh_discovery import config
from mmh_discovery.search.cache import ResponseCache

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class AllKeysExhausted(RuntimeError):
    """Every key in the pool returned 432 (quota exhausted) during this run."""


class Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


class TavilyKeyPool:
    def __init__(
        self,
        keys: list[str],
        *,
        budget: int = config.SEARCH_RUN_CREDIT_BUDGET,
        sleep: Sleeper = time.sleep,
        transport: httpx.BaseTransport | None = None,
        cache: ResponseCache | None = None,
        offline: bool = False,
    ) -> None:
        if not keys and not offline:
            raise ValueError("TAVILY_API_KEYS not set in .env - create keys at "
                             "https://app.tavily.com and add them comma-separated.")
        self.keys = list(keys)
        self.budget = budget
        self.credits_used = 0
        self.cache_hits = 0
        self.dropped: set[str] = set()
        self._cycle = itertools.cycle(self.keys) if keys else iter(())
        self._sleep = sleep
        self._cache = cache
        self._offline = offline
        self._client = httpx.Client(
            timeout=config.SEARCH_TIMEOUT_SECONDS, transport=transport)

    @property
    def budget_exhausted(self) -> bool:
        return self.credits_used >= self.budget

    def close(self) -> None:
        self._client.close()

    def _payload(self, query: str) -> dict:
        return {
            "query": query, "topic": "general", "search_depth": "basic",
            "max_results": config.SEARCH_MAX_RESULTS,
            "include_answer": False, "include_raw_content": False,
        }

    def cache_get(self, query: str) -> list[dict] | None:
        """Peek the response cache without touching budget or counters."""
        return self._cache.get(query) if self._cache is not None else None

    def search(self, query: str) -> list[dict]:
        """One Tavily search, normalized to [{title, url, content}].

        Cache first (free, does not consume budget). Returns [] (never raises)
        on transient failure so one bad query cannot kill the run; raises
        AllKeysExhausted only when no key remains.
        """
        if self._cache is not None:
            cached = self._cache.get(query)
            if cached is not None:
                self.cache_hits += 1
                return cached
            if self._offline:
                return []
        if self.budget_exhausted:
            return []
        if len(self.dropped) == len(self.keys):
            raise AllKeysExhausted("all Tavily keys are out of credits; add more to "
                                   "TAVILY_API_KEYS")
        payload = self._payload(query)
        for _ in range(4 * len(self.keys)):
            key = next(self._cycle)
            if key in self.dropped:
                continue
            try:
                resp = self._client.post(
                    TAVILY_SEARCH_URL, json=payload,
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"})
            except httpx.HTTPError:
                self._sleep(2)
                continue
            if resp.status_code == 429:  # rate limit: back off, rotate
                self._sleep(3)
                continue
            if resp.status_code == 432:  # quota exhausted for this key
                self.dropped.add(key)
                if len(self.dropped) == len(self.keys):
                    raise AllKeysExhausted("all Tavily keys are out of credits; add "
                                           "more to TAVILY_API_KEYS")
                continue
            if resp.status_code >= 400:
                self._sleep(2)
                continue
            self.credits_used += 1
            self._sleep(config.SEARCH_SLEEP_SECONDS)
            results = [
                {"title": r.get("title"), "url": r.get("url"),
                 "content": r.get("content") or r.get("snippet")}
                for r in resp.json().get("results", [])
            ]
            if self._cache is not None:
                self._cache.put(query, results)
            return results
        return []
