"""Adaptive context-budget retry in extract_domain's LLM call."""
from mmh_discovery.extractor import extract as extract_mod
from mmh_discovery.extractor.extract import ExtractionStats, _chat_with_budget
from mmh_discovery.extractor.llm_client import LLMError, LLMResponse


class FakeLLM:
    def __init__(self, overflow_first: bool, overflow_times: int = 1):
        self.overflow_first = overflow_first
        self.overflow_times = overflow_times
        self.corpus_lengths: list[int] = []

    def chat(self, system, corpus):
        self.corpus_lengths.append(len(corpus))
        if self.overflow_first and len(self.corpus_lengths) <= self.overflow_times:
            raise LLMError(
                'LLM HTTP 400: {"error":{"message":"This model\'s maximum context length '
                "is 131072 tokens. However, you requested 8192 output tokens and your "
                "prompt contains at least 122881 input tokens, for a total of at least "
                '131073 tokens.'
            )
        return LLMResponse(content="{}", prompt_tokens=1, completion_tokens=1, latency_ms=1)


def test_overflow_retry_shrinks_corpus_by_observed_density():
    llm = FakeLLM(overflow_first=True)
    corpus = "x" * 350_000
    stats = ExtractionStats()
    resp = _chat_with_budget(llm, corpus, stats)
    assert resp.content == "{}"
    # server reported >=122881 tokens (a lower bound); retry scales the corpus
    # by 0.8 * (131072 - 8192 - 6000) / 122881 ~= 0.76
    assert len(llm.corpus_lengths) == 2
    shrunk = llm.corpus_lengths[1]
    assert shrunk < llm.corpus_lengths[0]
    # even at the lower-bound density, the shrunk prompt must fit the window
    assert shrunk * (122_881 / 350_000) <= 131_072 - 8_192
    assert stats.truncated


def test_repeated_overflow_keeps_shrinking():
    llm = FakeLLM(overflow_first=True, overflow_times=2)
    stats = ExtractionStats()
    resp = _chat_with_budget(llm, "x" * 350_000, stats)
    assert resp.content == "{}"
    assert len(llm.corpus_lengths) == 3
    assert llm.corpus_lengths[2] < llm.corpus_lengths[1] < llm.corpus_lengths[0]
    assert stats.truncated


def test_giving_up_below_min_corpus():
    # 4 consecutive overflows of a small-ish corpus shrinks below 20k: must raise
    llm = FakeLLM(overflow_first=True, overflow_times=99)
    try:
        _chat_with_budget(llm, "x" * 60_000, ExtractionStats())
    except LLMError as exc:
        assert "400" in str(exc)
    else:
        raise AssertionError("expected LLMError")


def test_non_overflow_error_propagates():
    class Boom(FakeLLM):
        def chat(self, system, corpus):
            raise LLMError("LLM HTTP 500: bad gateway")

    stats = ExtractionStats()
    try:
        _chat_with_budget(Boom(overflow_first=False), "corpus", stats)
    except LLMError as exc:
        assert "500" in str(exc)
    else:
        raise AssertionError("expected LLMError")


def test_no_overflow_single_call(monkeypatch):
    monkeypatch.setattr(extract_mod.config, "EXTRACT_HTML_CAP_CHARS", 350_000)
    llm = FakeLLM(overflow_first=False)
    _chat_with_budget(llm, "hello", ExtractionStats())
    assert llm.corpus_lengths == [5]
