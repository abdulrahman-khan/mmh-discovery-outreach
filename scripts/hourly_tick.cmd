@echo off
rem Hourly pipeline tick: re-queue due candidates, seed new websites, process
rem a bounded batch. Safe to overlap? No - run_once claims jobs with
rem FOR UPDATE SKIP LOCKED and reclaims orphaned runs >2h, so concurrent
rem ticks drain the queue cooperatively.
cd /d C:\Users\monamoe\Documents\1_Programming\mmh-discovery-outreach
uv run python scripts/seed_crawl_jobs.py >> data\logs\cron.log 2>&1
uv run python -m mmh_discovery.pipeline.run_once --limit 40 >> data\logs\cron.log 2>&1
