# Startup Guide

Fresh machine to first OSM import.

## Prereqs

- Python 3.12+
- GNU Make
- `psql` client
- A Supabase project (free tier is fine)

## Install

1. `make setup` - creates `.venv`, installs `db,scrape,dev` extras.
2. `copy .env.example .env` (Windows) or `cp .env.example .env` (POSIX).
3. Fill `DATABASE_URL` in `.env`. Supabase: Settings -> Database -> Connection string.

## Verify

1. `make lint`
2. `make test` - expect 11 passed.

## First run

1. `make migrate` - applies `supabase/migrations/0001_init.sql`.
2. `make osm-import` - dry-run, writes `data/runs/<ts>/osm_candidates.json`.
3. Land rows in the DB: `.venv\Scripts\python -m mmh_discovery.discovery.osm --write-db`.

## Layout

- `src/mmh_discovery/core/` - url_guard, scrape_outcome, naming.
- `src/mmh_discovery/discovery/` - per-source importers.
- `supabase/migrations/` - append-only schema files.

Hard bans and compliance rules live in `README.md`.
