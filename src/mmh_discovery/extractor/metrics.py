"""Per-run metrics: JSONL per domain under data/runs/{run_id}/, aggregate row
in extraction_runs. Token usage is the cost-tracking mechanism (DGX is
self-hosted; no per-call USD price is known, so llm_cost_usd stays NULL).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from mmh_discovery.extractor.extract import ExtractionStats


class RunMetrics:
    def __init__(self, run_id: str, data_dir: str | Path) -> None:
        self.run_id = run_id
        self.dir = Path(data_dir) / "runs" / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "extract.jsonl"
        self.started_at = datetime.now(UTC)
        self.pages_seen = 0
        self.orgs_updated = 0
        self.rejected = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.errors: list[str] = []

    def record_domain(
        self,
        domain: str,
        org_id: str | None,
        stats: ExtractionStats | None,
        contacts: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "domain": domain,
            "org_id": org_id,
            "ok": error is None,
            "error": error,
            "contacts": contacts or {},
            "dropped": stats.dropped if stats else {},
            "prompt_tokens": stats.prompt_tokens if stats else 0,
            "completion_tokens": stats.completion_tokens if stats else 0,
            "latency_ms": stats.latency_ms if stats else 0,
            "corpus_chars": stats.corpus_chars if stats else 0,
            "truncated": stats.truncated if stats else False,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if stats:
            self.prompt_tokens += stats.prompt_tokens
            self.completion_tokens += stats.completion_tokens
            self.pages_seen += 1
        if error:
            self.rejected += 1
            self.errors.append(f"{domain}: {error}")
        else:
            self.orgs_updated += 1

    def record_pages(self, n: int) -> None:
        self.pages_seen += n

    def finalize(self, conn: psycopg.Connection, error: str | None = None) -> None:
        """Write the per-run aggregate into extraction_runs.
        Token totals ride in `error` as JSON when the run itself succeeded;
        a fatal error string wins. llm_cost_usd stays NULL (self-hosted DGX)."""
        detail = error
        if detail is None and (self.errors or self.prompt_tokens or self.completion_tokens):
            detail = json.dumps(
                {
                    "tokens": {"prompt": self.prompt_tokens, "completion": self.completion_tokens},
                    "errors": self.errors[:20],
                }
            )
        conn.execute(
            """
            insert into extraction_runs (run_id, started_at, finished_at, pages_seen,
                                         orgs_created, orgs_updated, rejected, llm_cost_usd, error)
            values (%s, %s, now(), %s, 0, %s, %s, NULL, %s)
            """,
            (
                self.run_id,
                self.started_at,
                self.pages_seen,
                self.orgs_updated,
                self.rejected,
                detail,
            ),
        )
