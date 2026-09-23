"""Shared upsert of normalized discovery rows into org_candidates."""
from __future__ import annotations

import json

import psycopg

from mmh_discovery import config


def upsert(candidates: list[dict]) -> int:
    rows = [
        (
            c["source_id"], c["external_id"], c["name"], c["phone"], c["email"],
            c["website"], c["address_line1"], c["city"], c["province"],
            c["postal_code"], c["lat"], c["lng"],
            json.dumps(c["social"]), json.dumps(c["raw"]),
        )
        for c in candidates
    ]
    with psycopg.connect(config.DATABASE_URL) as conn, conn.transaction():
        conn.cursor().executemany(
            """
            insert into org_candidates (
                source_id, external_id, name, phone, email, website,
                address_line1, city, province, postal_code, lat, lng,
                social, raw
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            on conflict (source_id, external_id) do update set
                name = coalesce(excluded.name, org_candidates.name),
                phone = coalesce(excluded.phone, org_candidates.phone),
                email = coalesce(excluded.email, org_candidates.email),
                website = coalesce(excluded.website, org_candidates.website),
                city = coalesce(excluded.city, org_candidates.city),
                province = coalesce(excluded.province, org_candidates.province),
                social = excluded.social,
                raw = excluded.raw
            """,
            rows,
        )
    return len(rows)
