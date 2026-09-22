.PHONY: help setup lint test osm-import migrate seed-jobs crawl-once migrate-apply search-once

help:
	@echo setup          - uv sync \(venv + all extras\)
	@echo lint           - ruff check
	@echo test           - pytest
	@echo osm-import     - dry-run OSM discovery importer (writes data/runs/)
	@echo migrate        - apply supabase/migrations via scripts/migrate.py
	@echo migrate-apply  - alias of migrate
	@echo seed-jobs      - queue crawl_jobs from org_candidates websites
	@echo crawl-once     - claim queued jobs, crawl, LLM-extract, persist
	@echo search-once    - Tavily enrichment pass -> enrichment_proposals \(dry writes only without --apply\)

setup:
	uv sync --all-extras

lint:
	uv run ruff check src tests

test:
	uv run pytest

osm-import:
	uv run python -m mmh_discovery.discovery.osm

migrate:
	uv run python scripts/migrate.py

migrate-apply: migrate

seed-jobs:
	uv run python scripts/seed_crawl_jobs.py

crawl-once:
	uv run python -m mmh_discovery.pipeline.run_once

search-once:
	uv run python -m mmh_discovery.search.run --limit 10
