"""Per-entity search query templates.

Unlike the tsw discovery agent (LLM-generated dork queries for topic discovery),
MMH enrichment is per-entity: the target already has a name and usually a site
domain. Queries are deterministic templates, ordered by expected yield; the
caller stops as soon as the needed fields are found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchTarget:
    """One enrichment target: a queue row or an address-less org."""
    org_id: str | None
    candidate_id: str | None
    domain: str | None
    name: str
    website: str | None
    city: str | None
    missing: tuple[str, ...]  # fields to hunt: email, phone, province, city


def site_slug(website: str | None, domain: str | None) -> str | None:
    site = website or (f"https://{domain}" if domain else None)
    if not site:
        return None
    return re.sub(r"^https?://(www\.)?", "", site).strip("/") or None


def build_query_slots(target: SearchTarget) -> list[tuple[str, str]]:
    """(template, query) slots ordered by expected yield; max 3. The template
    tags the (target x template) ledger slot: novelty lives in the ledger, not
    in the generator (DEVNOTES/RESEARCH-search-scrape-architectures.md §6.3)."""
    slots: list[tuple[str, str]] = []
    site = site_slug(target.website, target.domain)
    if site:
        slots.append(("site_contact", f"{site} contact email phone"))
    name = target.name.strip()
    if name:
        slots.append(("name_contact", f'"{name}" mosque contact'))
        if target.city:
            slots.append(("name_city", f'"{name}" {target.city} mosque'))
        elif len(slots) < 3:
            slots.append(("name_canada", f'"{name}" mosque Canada'))
    return slots[:3]


def build_queries(target: SearchTarget) -> list[str]:
    """Query templates ordered by expected yield; max 3."""
    return [q for _, q in build_query_slots(target)]
