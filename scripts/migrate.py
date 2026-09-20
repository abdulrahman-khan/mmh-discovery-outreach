"""Apply supabase/migrations/*.sql in filename order using psycopg3.

Usage: python scripts/migrate.py [--dry-run]
Reads DATABASE_URL from .env (or environment).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env(ROOT / ".env")
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        print("DATABASE_URL missing", file=sys.stderr)
        return 1

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("no migrations found", file=sys.stderr)
        return 1

    if args.dry_run:
        for f in files:
            print(f"would apply: {f.name}")
        return 0

    with psycopg.connect(dsn, autocommit=True) as conn:
        for f in files:
            print(f"applying: {f.name}")
            conn.execute(f.read_text(encoding="utf-8"))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
