"""Extraction prompt. One call per domain; pages joined with explicit markers.

PROMPT_VERSION stamps every persisted extraction (method = f"llm:{PROMPT_VERSION}")
so re-extraction passes can be distinguished in field_provenance.
"""
from __future__ import annotations

PROMPT_VERSION = "v1"

PAGE_SEPARATOR = "--- page: {url} ---"

SYSTEM = """\
You extract contact information for one organisation (a masjid/mosque) from the
HTML of its own website pages. Multiple pages are concatenated; each page starts
with a line of the form:

--- page: https://example.org/contact ---

Return ONLY a JSON object, no prose, with exactly these keys:

{
  "emails":        [{"value": "...", "source_url": "..."}],
  "phones":        [{"value": "...", "source_url": "..."}],
  "socials":       [{"platform": "...", "value": "...", "source_url": "..."}],
  "contact_forms": [{"value": "...", "source_url": "..."}],
  "raw_context":   [{"text": "...", "source_url": "..."}]
}

Rules:
- "value" for emails/phones/contact_forms and "source_url" must be taken
  VERBATIM from the page text: the exact email/phone string and the exact page
  URL it appears under. Do not normalise, reformat, or invent.
- "contact_forms" values are the page URLs that host a contact form.
- "socials": platform is one of facebook, instagram, twitter, x, youtube, tiktok,
  whatsapp, linkedin. "value" is the profile URL as it appears in the HTML.
  Record every distinct profile link you find; do not crawl or expand them.
- Keep EVERY distinct email, phone, social profile, and contact form you find.
  Do not pick a "primary" one.
- "raw_context": short factual excerpts about the organisation (services,
  prayer schedule notes, programmes, history, leadership) that a later
  summariser can use. Paraphrase is allowed here; still attach source_url.
- Never include data from aggregator or third-party sites; only the given pages.
- If a category has nothing, use an empty list.
"""


def user_prompt(pages: list[tuple[str, str]]) -> str:
    """Join (url, html) pairs with `--- page: {url} ---` separator lines."""
    parts = []
    for url, html in pages:
        parts.append(PAGE_SEPARATOR.format(url=url))
        parts.append(html)
    return "\n".join(parts)
