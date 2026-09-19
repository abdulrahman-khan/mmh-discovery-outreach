.PHONY: help setup lint test osm-import migrate

help:
	@echo setup        - create .venv and install dev dependencies
	@echo lint         - ruff check
	@echo test         - pytest
	@echo osm-import   - dry-run OSM discovery importer (writes data/runs/)
	@echo migrate      - apply supabase/migrations via psql (needs DATABASE_URL)

setup:
	python -m venv .venv
	.venv\Scripts\python -m pip install -e ".[db,scrape,dev]"

lint:
	.venv\Scripts\python -m ruff check src tests

test:
	.venv\Scripts\python -m pytest

osm-import:
	.venv\Scripts\python -m mmh_discovery.discovery.osm

migrate:
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f supabase/migrations/0001_init.sql
