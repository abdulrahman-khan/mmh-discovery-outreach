"""Filesystem cache for Tavily search responses.

Purpose: iterate on scoring/vetting without burning credits. Every live search
response is stored under DATA_DIR/search_cache/<sha256(query)>.json; repeats
replay from disk (zero credits). The cache directory sits under gitignored
data/ - cached search content is scraped data and never gets committed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def query_key(query: str) -> str:
    """Ledger/cache identity for a query: normalized string, sha256 prefix.
    SerpApi's documented cache key is 'query + all params' (§5 of the research
    note); our searches are query-only besides fixed params, so this matches."""
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:32]


class ResponseCache:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)

    def key(self, query: str) -> str:
        return query_key(query)

    def get(self, query: str) -> list[dict] | None:
        path = self.dir / f"{self.key(query)}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, list) else None

    def put(self, query: str, results: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{self.key(query)}.json"
        path.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
