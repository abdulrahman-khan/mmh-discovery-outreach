# Startup Guide

Fresh machine to first pipeline run.

## Prereqs

- [uv](https://docs.astral.sh/uv/) (installs the pinned Python 3.12 itself)
- GNU Make
- A Supabase project (free tier is fine)
- Network path to the DGX vLLM server (Tailscale) for the extract step

## Install

1. `make setup` - `uv sync --all-extras`, creates `.venv` with pinned Python.
2. `copy .env.example .env` (Windows) or `cp .env.example .env` (POSIX).
3. Fill `DATABASE_URL` in `.env`. Supabase: Settings -> Database -> Connection
   string -> Session pooler (the direct host is IPv6-only).
4. LLM settings (`LLM_BASE_URL`, `LLM_MODEL`) already match the DGX defaults;
   the server is keyless today.

## Verify

1. `make lint`
2. `make test`

## First run

1. `make migrate` - applies `supabase/migrations/*.sql` via `scripts/migrate.py`.
2. `make osm-import` - dry-run, writes `data/runs/<ts>/osm_candidates.json`.
3. Land rows in the DB: `uv run python -m mmh_discovery.discovery.osm --write-db`.
4. `make seed-jobs` - idempotently queues one `crawl_jobs` row per candidate
   website (blocklisted hosts skipped).
5. `make crawl-once` - claims queued jobs, BFS-crawls each domain, runs one
   LLM extraction per domain, persists contacts + provenance.
   Flags: `uv run python -m mmh_discovery.pipeline.run_once --limit N --dry-run`.

## Layout

- `src/mmh_discovery/core/` - url_guard, scrape_outcome, naming.
- `src/mmh_discovery/discovery/` - per-source importers.
- `src/mmh_discovery/crawler/` - robots, rate limiter, BFS scope, fetcher.
- `src/mmh_discovery/extractor/` - LLM client, prompt, verbatim check, writer, metrics.
- `src/mmh_discovery/pipeline/` - run_once worker.
- `supabase/migrations/` - append-only schema files.

Hard bans and compliance rules live in `README.md`.
