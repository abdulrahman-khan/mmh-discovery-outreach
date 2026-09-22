"""Regex field extraction over search hits (promoted from scripts/enrich_queue.py).

Deterministic, no LLM: emails/phones/FSA/"City, Province" pulled from each hit's
title + url + snippet. Preference rules and blocklist carried over verbatim from
the session-6 pass that was validated by hand against 55 queue rows.
"""
from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Snippets glue words without spaces ("...gmail.comemail..."): a greedy regex
# cannot tell a run-on from a long TLD, so the last domain label is truncated
# to the longest known TLD prefix when it is not itself a known TLD
# (sweep-1 regression: 'masjid.iqaluit@gmail.comemail' reached 'verified').
KNOWN_TLDS = {
    "com", "ca", "org", "net", "edu", "gov", "io", "us", "uk", "co", "info",
    "biz", "me", "dev", "app", "xyz", "online", "site", "live", "store",
    "email", "church", "islam", "mosque", "de", "fr", "nl", "au", "in", "pk",
    "ir", "sa", "eg", "tr", "my", "id", "eu", "ch", "it", "es", "pl",
}


def _truncate_runon_tld(email: str) -> str:
    user, _, domain = email.rpartition("@")
    labels = domain.split(".")
    last = labels[-1]
    if last not in KNOWN_TLDS:
        prefix = next((t for t in sorted(KNOWN_TLDS, key=len, reverse=True)
                       if last.startswith(t) and len(last) > len(t)), None)
        if prefix:
            labels[-1] = prefix
            email = f"{user}@{'.'.join(labels)}"
    return email


PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})(?!\d)")
FSA_RE = re.compile(r"\b([A-PR-Wa-pr-w]\d[A-PR-Za-pr-w])\s?\d[A-PR-Za-pr-w]\d\b")
CITY_PROV_RE = re.compile(
    r"\b([A-Z][A-Za-z'.\- ]{2,28}?),\s*(ON|BC|AB|SK|MB|QC|NS|NB|NL|PE|YT|NT|NU)\b")

BAD_EMAIL_SUBS = ("example.", "sentry", "wixpress", ".png", ".jpg", ".gif", ".webp", ".css",
                  ".js", "yourdomain", "domain.com", "email.com", "sentry.io", "@2x",
                  "no-reply", "noreply", "@duckduckgo.com", "@google.com", "wixpress.com")

# Preferred local-parts: masjid contact addresses cluster on these.
PREFERRED_LOCALS = ("info", "admin", "contact", "office", "masjid", "administrator",
                    "secretary", "imam")

US_AREA_CODES = {  # snippet-level guard: US numbers share the +1 format
    "201", "212", "213", "305", "312", "404", "415", "617", "646", "702", "718",
    "713", "214", "310", "323", "469", "512", "602", "614", "619", "704", "727",
    "971", "44", "20",
}


def clean_emails(text: str) -> list[str]:
    emails = [_truncate_runon_tld(e.lower()) for e in EMAIL_RE.findall(text)]
    emails = [e for e in emails if not any(b in e for b in BAD_EMAIL_SUBS)
              and not re.search(r"\.(png|jpe?g|gif|webp|css|js|svg)$", e)]
    # dedupe, preferred local-parts first, then shortest
    return sorted(dict.fromkeys(emails),
                  key=lambda e: (e.split("@")[0] not in PREFERRED_LOCALS, len(e)))


def first_phone(text: str) -> str | None:
    for m in PHONE_RE.finditer(text):
        # area codes 204-902 minus a few US ones; a crude but effective CA skew
        if m.group(1) in US_AREA_CODES:
            continue
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def first_fsa(text: str) -> str | None:
    m = FSA_RE.search(text)
    return m.group(1).upper() if m else None


def first_city_prov(text: str) -> tuple[str, str] | None:
    for m in CITY_PROV_RE.finditer(text):
        city = m.group(1).strip().title()
        if len(city) > 2:
            return (city, m.group(2))
    return None


def extract_fields(hit: dict) -> dict:
    """All fields found in one hit's text, each with the hit as provenance."""
    text = " ".join(str(hit.get(k) or "") for k in ("title", "url", "content"))
    cp = first_city_prov(text)
    return {
        "emails": clean_emails(text),
        "phone": first_phone(text),
        "fsa": first_fsa(text),
        "city": cp[0] if cp else None,
        "province": cp[1] if cp else None,
    }
