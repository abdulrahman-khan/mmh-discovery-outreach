"""Verbatim-match checks (D-008: LLM output must match the fetched HTML).

URLs are checked against the URLs actually present in the corpus, compared
after HTML-entity decoding and query/trailing-slash trimming (the LLM
legitimately trims `?lang=en`-style params and `&amp;` differs from `&`).
Emails and phones are checked after aggressive normalisation (strip every
non-alphanumeric char, lowercase) so "mailto:" prefixes, tel separators, and
zero-width/whitespace noise don't matter.
A value that cannot be found in any fetched page is dropped, never coerced.
"""
from __future__ import annotations

import html
import re
from functools import lru_cache

_URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""")


@lru_cache(maxsize=8)
def _corpus_url_parts(hay: str) -> tuple[tuple[str, str], ...]:
    return tuple(_split_url(u) for u in _URL_RE.findall(hay))


def _split_url(value: str) -> tuple[str, str]:
    """html-unescape, drop the fragment, return (path_without_trailing_slash, query)."""
    value = html.unescape(value).split("#", 1)[0]
    path, _, query = value.partition("?")
    return path.rstrip("/").lower(), query


def contains_url(needle: str, hay: str) -> bool:
    """URL check: path must equal some corpus URL's path exactly; the needle's
    query must be a prefix of that corpus URL's query (the LLM legitimately
    trims params like `?lang=en`; it may not invent or reorder them)."""
    n_path, n_query = _split_url(needle)
    if not n_path.startswith(("http://", "https://")):
        return False
    for cand in _corpus_url_parts(hay):
        c_path, c_query = cand
        if c_path == n_path and c_query.startswith(n_query):
            return True
    return False


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def contains_normalized(needle: str, hay: str) -> bool:
    """Normalised substring check (for emails/phones): keep alphanumerics only,
    lowercase both sides. Empty needles never match."""
    n = _normalise(needle)
    return bool(n) and n in _normalise(hay)


# Kept for tests and any caller that needs a raw substring check.
def contains_exact(needle: str, hay: str) -> bool:
    return needle in hay
