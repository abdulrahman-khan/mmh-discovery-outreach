"""Persist a validated ExtractionResult to Postgres.

- source_records: one row per (URL, run), insert-only audit log (no HTML,
  content_hash only).
- contacts: upsert by (org_id, kind, value); every distinct value is kept,
  no auto-primary (human review in Retool picks the primary later).
- field_provenance: one row per contact (entity_type='contact', field=kind),
  pointing at the source record for the page the value was found on.
- organizations.raw_context: rewritten each run as `--- {url} ---` blocks.
"""
from __future__ import annotations

import hashlib
import logging

import psycopg

from mmh_discovery.extractor.prompt import PROMPT_VERSION
from mmh_discovery.extractor.schema import ExtractionResult

log = logging.getLogger(__name__)

METHOD = f"llm:{PROMPT_VERSION}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _insert_source_record(
    conn: psycopg.Connection, url: str, run_id: str, html: str, http_status: int | None
) -> str:
    rec_id = conn.execute(
        """
        insert into source_records (source_id, external_id, url, http_status, content_hash, meta)
        values ('web', %s, %s, %s, %s, %s)
        returning id
        """,
        (
            f"{run_id}:{url}",
            url,
            http_status,
            _sha256(html),
            psycopg.types.json.Jsonb({"run_id": run_id, "method": METHOD}),
        ),
    ).fetchone()[0]
    return str(rec_id)


def _upsert_contact(
    conn: psycopg.Connection, org_id: str, kind: str, value: str, label: str | None
) -> str:
    return str(
        conn.execute(
            """
            insert into contacts (org_id, kind, value, label)
            values (%s, %s, %s, %s)
            on conflict (org_id, kind, value)
            do update set updated_at = now(), label = coalesce(excluded.label, contacts.label)
            returning id
            """,
            (org_id, kind, value, label),
        ).fetchone()[0]
    )


def _upsert_provenance(
    conn: psycopg.Connection, entity_id: str, field: str, source_record_id: str
) -> None:
    conn.execute(
        """
        insert into field_provenance (entity_type, entity_id, field, source_record_id, method)
        values ('contact', %s, %s, %s, %s)
        on conflict (entity_type, entity_id, field)
        do update set source_record_id = excluded.source_record_id,
                      method = excluded.method,
                      created_at = now()
        """,
        (entity_id, field, source_record_id, METHOD),
    )


def render_raw_context(result: ExtractionResult) -> str:
    """`--- {url} ---\\n{text}` blocks joined by blank lines."""
    return "\n\n".join(
        f"--- {item.source_url} ---\n{item.text}" for item in result.raw_context
    )


def persist_extraction(
    conn: psycopg.Connection,
    org_id: str,
    result: ExtractionResult,
    run_id: str,
    pages: list[tuple[str, int | None, str]],
) -> dict[str, int]:
    """pages: list of (url, http_status, html) for the crawled pages.
    Returns counts of persisted contacts per kind."""
    record_ids: dict[str, str] = {}
    for url, http_status, html in pages:
        record_ids[url] = _insert_source_record(conn, url, run_id, html, http_status)

    def source_for(url: str) -> str | None:
        rec = record_ids.get(url)
        if rec is None:
            log.warning("source_url not among crawled pages, provenance left null: %s", url)
        return rec

    counts: dict[str, int] = {}
    groups = [
        ("email", [ (i, None) for i in result.emails ]),
        ("phone", [ (i, None) for i in result.phones ]),
        ("social", [ (i, i.platform) for i in result.socials ]),
        ("contact_form", [ (i, None) for i in result.contact_forms ]),
    ]
    for kind, items in groups:
        n = 0
        for item, label in items:
            contact_id = _upsert_contact(conn, org_id, kind, item.value, label)
            rec = source_for(item.source_url)
            if rec:
                _upsert_provenance(conn, contact_id, kind, rec)
            n += 1
        counts[kind] = n

    raw = render_raw_context(result)
    if raw:
        conn.execute(
            "update organizations set raw_context = %s, updated_at = now() where id = %s",
            (raw, org_id),
        )
    else:
        conn.execute("update organizations set updated_at = now() where id = %s", (org_id,))
    return counts
