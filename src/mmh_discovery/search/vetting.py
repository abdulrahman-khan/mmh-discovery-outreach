"""Vetting rules: when may a found value be applied without a human?

Encodes the session-6 hand rule: accept an email only if domain-matched or
confirmed on the org's own pages. FSA-derived province from the org's own page
is authoritative (Canada Post). Everything else stays 'proposed' for review.
Rejected values never reach the proposals table as apply-eligible.
"""
from __future__ import annotations

from urllib.parse import urlparse

# vetting outcomes
VERIFIED = "verified"
PROPOSED = "proposed"


def apex(host: str) -> str:
    parts = host.lower().strip(".").removeprefix("www.").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def org_apex(website: str | None, domain: str | None) -> str | None:
    src = website or (f"https://{domain}" if domain else None)
    if not src:
        return None
    host = urlparse(src if "://" in src else f"https://{src}").netloc
    return apex(host) if host else None


def on_org_page(source_url: str, apex_value: str | None) -> bool:
    if not apex_value:
        return False
    return apex(urlparse(source_url).netloc) == apex_value


def vet(field: str, value: str, source_url: str, *,
        website: str | None = None, domain: str | None = None,
        city_ok: frozenset[str] | None = None) -> tuple[str, str]:
    """Return (vetting, rule). city_ok: lowercased city names with a known
    province (backfill_province.CITY keys); a city not in the table cannot be
    trusted for its province pair alone -> proposed."""
    org = org_apex(website, domain)
    own = on_org_page(source_url, org)
    if field == "email":
        email_apex = apex(value.split("@", 1)[1]) if "@" in value else ""
        if org and email_apex == org:
            return (VERIFIED, "email_domain_match")
        if own:
            return (VERIFIED, "email_on_own_page")
        return (PROPOSED, "email_third_party")
    if field == "phone":
        return (VERIFIED, "phone_on_own_page") if own else (PROPOSED, "phone_third_party")
    if field == "province":
        # FSA-derived province (value == FSA) on the org's own page is authoritative.
        if own:
            return (VERIFIED, "province_fsa_own_page")
        return (PROPOSED, "province_snippet")
    if field == "city":
        if city_ok is not None and value.lower() in city_ok:
            return (PROPOSED, "city_known_needs_pair")
        return (PROPOSED, "city_unknown")
    return (PROPOSED, "unreviewed_field")


def vet_city_prov(city: str, province: str, *,
                  city_ok: dict[str, str]) -> tuple[str, str]:
    """"City, XX" snippet: verified only when the curated city table agrees
    with the snippet's province (same derivation backfill_province applies)."""
    known = city_ok.get(city.lower())
    if known and known == province:
        return (VERIFIED, "city_table_agrees")
    return (PROPOSED, "city_snippet_unconfirmed")
