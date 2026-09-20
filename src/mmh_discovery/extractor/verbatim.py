"""Verbatim-match checks (D-008: LLM output must match the fetched HTML).

URLs are checked exactly; emails and phones are checked after aggressive
normalisation (strip every non-alphanumeric char, lowercase) so "mailto:"
prefixes, tel separators, and zero-width/whitespace noise don't matter.
A value that cannot be found in any fetched page is dropped, never coerced.
"""
from __future__ import annotations

import re


def contains_exact(needle: str, hay: str) -> bool:
    """Exact substring check (for URLs)."""
    return needle in hay


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def contains_normalized(needle: str, hay: str) -> bool:
    """Normalised substring check (for emails/phones): keep alphanumerics only,
    lowercase both sides. Empty needles never match."""
    n = _normalise(needle)
    return bool(n) and n in _normalise(hay)
