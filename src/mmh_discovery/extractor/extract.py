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
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from mmh_discovery import config
from mmh_discovery.extractor.llm_client import LLMClient, LLMError, LLMResponse
from mmh_discovery.extractor.prompt import SYSTEM, user_prompt
from mmh_discovery.extractor.schema import ContactItem, ExtractionResult, SocialItem
from mmh_discovery.extractor.verbatim import contains_normalized, contains_url

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


_OVERFLOW_INPUT_RE = re.compile(r"prompt contains at least (\d+) input tokens")
_BUDGET_SAFETY_TOKENS = 6_000  # headroom for the chat template wrapper + thinking
_BUDGET_HEADROOM = 0.8  # "at least N tokens" is a lower bound; leave slack
_BUDGET_MIN_CHARS = 20_000  # below this a corpus is too mutilated to extract


def _chat_with_budget(llm: LLMClient, corpus: str, stats: ExtractionStats) -> LLMResponse:
    """Call the LLM; on a context-overflow HTTP 400, shrink the corpus and
    retry until it fits (bounded). vLLM reports `at least N` tokens, where
    N = window - max_tokens: a lower bound, so one shrink from N under-
    corrects on dense pages (observed 1.8 chars/token on Wix inline JSON).
    Each iteration re-reads N, so the loop converges in a few cheap 400s."""
    budget = len(corpus)
    last_exc: LLMError | None = None
    for attempt in range(4):
        try:
            response = llm.chat(SYSTEM, corpus[:budget])
            if budget < len(corpus):
                stats.truncated = True
            return response
        except LLMError as exc:
            match = _OVERFLOW_INPUT_RE.search(str(exc))
            if not match:
                raise
            last_exc = exc
            reported = int(match.group(1))
            available = (config.LLM_MAX_MODEL_LEN - config.LLM_MAX_TOKENS
                         - _BUDGET_SAFETY_TOKENS)
            budget = int(budget * min(_BUDGET_HEADROOM * available / reported, 0.9))
            log.warning("context overflow (attempt %d, server: >=%d tokens); retrying at %d chars",
                        attempt + 1, reported, budget)
            if budget < _BUDGET_MIN_CHARS:
                break
    assert last_exc is not None
    raise last_exc


def _filter_items(items: list[ContactItem], corpus: str, normalised: bool,
                  category: str, stats: ExtractionStats) -> list[ContactItem]:
    check = contains_normalized if normalised else contains_url
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

    response = _chat_with_budget(llm, corpus, stats)
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
