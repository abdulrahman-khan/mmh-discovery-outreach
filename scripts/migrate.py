"""Apply supabase/migrations/*.sql in filename order using psycopg3.

Usage: python scripts/migrate.py [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import psycopg

from mmh_discovery import config

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL missing (set in .env)")

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit("no migrations found")

    if args.dry_run:
        for f in files:
            print(f"would apply: {f.name}")
        return 0

    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        for f in files:
            print(f"applying: {f.name}")
            conn.execute(f.read_text(encoding="utf-8"))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
