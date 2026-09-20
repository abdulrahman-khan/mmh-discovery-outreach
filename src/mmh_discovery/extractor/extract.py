"""One LLM call per domain: corpus -> validated ExtractionResult.

Pipeline: build corpus (pages joined with separators, truncated to
EXTRACT_HTML_CAP_CHARS) -> LLM call -> strip code fences defensively ->
json.loads -> verbatim filter against the fetched corpus -> Pydantic validate.
Bad JSON or schema violations raise ExtractionError (D-008: fail loud);
non-matching contact values are dropped and counted.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from mmh_discovery import config
from mmh_discovery.extractor.llm_client import LLMClient, LLMResponse
from mmh_discovery.extractor.prompt import SYSTEM, user_prompt
from mmh_discovery.extractor.schema import ContactItem, ExtractionResult, SocialItem
from mmh_discovery.extractor.verbatim import contains_exact, contains_normalized

log = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """LLM output was not parseable JSON or did not match the schema."""


@dataclass
class ExtractionStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    corpus_chars: int = 0
    truncated: bool = False
    dropped: dict[str, int] = field(default_factory=dict)

    def drop(self, category: str) -> None:
        self.dropped[category] = self.dropped.get(category, 0) + 1


def build_corpus(pages: list[tuple[str, str]]) -> tuple[str, bool]:
    """Concatenated corpus plus whether it exceeded the char cap.
    Truncation keeps whole pages while they fit, then hard-cuts the cap."""
    corpus = user_prompt(pages)
    if len(corpus) <= config.EXTRACT_HTML_CAP_CHARS:
        return corpus, False
    return corpus[: config.EXTRACT_HTML_CAP_CHARS], True


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def _filter_items(items: list[ContactItem], corpus: str, normalised: bool,
                  category: str, stats: ExtractionStats) -> list[ContactItem]:
    check = contains_normalized if normalised else contains_exact
    kept = []
    for item in items:
        if check(item.value, corpus):
            kept.append(item)
        else:
            stats.drop(category)
            log.debug("dropped non-verbatim %s: %r", category, item.value)
    return kept


def extract_domain(
    llm: LLMClient, pages: list[tuple[str, str]]
) -> tuple[ExtractionResult, ExtractionStats]:
    """pages: list of (url, html). Returns validated result + run stats."""
    corpus, truncated = build_corpus(pages)
    stats = ExtractionStats(corpus_chars=len(corpus), truncated=truncated)

    response: LLMResponse = llm.chat(SYSTEM, corpus)
    stats.prompt_tokens = response.prompt_tokens
    stats.completion_tokens = response.completion_tokens
    stats.latency_ms = response.latency_ms

    raw = _strip_code_fences(response.content)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"LLM returned invalid JSON: {exc}") from exc

    try:
        result = ExtractionResult.model_validate(payload)
    except ValidationError as exc:
        raise ExtractionError(f"LLM output failed schema validation: {exc}") from exc

    # Verbatim filter (raw_context is exempt: paraphrase allowed).
    result.emails = _filter_items(result.emails, corpus, True, "emails", stats)
    result.phones = _filter_items(result.phones, corpus, True, "phones", stats)
    result.socials = _filter_items(result.socials, corpus, False, "socials", stats)
    result.contact_forms = _filter_items(
        result.contact_forms, corpus, False, "contact_forms", stats
    )

    # Dedupe within category (same value seen on several pages).
    result.emails = _dedupe(result.emails)
    result.phones = _dedupe(result.phones)
    result.socials = _dedupe_socials(result.socials)
    result.contact_forms = _dedupe(result.contact_forms)
    return result, stats


def _dedupe(items: list[ContactItem]) -> list[ContactItem]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item.value.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _dedupe_socials(items: list[SocialItem]) -> list[SocialItem]:
    seen: set[tuple[str, str]] = set()
    out = []
    for item in items:
        key = (item.platform, item.value.strip().lower())
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
