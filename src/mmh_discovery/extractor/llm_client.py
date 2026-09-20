"""Minimal OpenAI-compatible chat client (httpx, no SDK).

Targets vLLM on the DGX: /chat/completions with response_format=json_object,
temperature 0. Token counts come straight from the response's usage field so
cost tracking stays in Python.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from mmh_discovery import config


class LLMError(RuntimeError):
    """LLM backend unreachable, errored, or returned an unexpected shape."""


@dataclass(frozen=True)
class LLMResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class LLMClient:
    def __init__(
        self,
        base_url: str = config.LLM_BASE_URL,
        model: str = config.LLM_MODEL,
        api_key: str = config.LLM_API_KEY,
        timeout: float = config.LLM_TIMEOUT_SECONDS,
    ) -> None:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.Client(headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def chat(self, system: str, user: str, max_tokens: int = config.LLM_MAX_TOKENS) -> LLMResponse:
        payload = {
            "model": self._model,
            "temperature": config.LLM_TEMPERATURE,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            # vLLM honors this for chatML chat templates (Qwen thinking switch).
            "chat_template_kwargs": {"enable_thinking": config.LLM_ENABLE_THINKING},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        start = time.monotonic()
        try:
            resp = self._client.post(f"{self._base_url}/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code >= 400:
            raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError(f"unexpected LLM response shape: {exc}") from exc
        usage = data.get("usage") or {}
        content = data["choices"][0]["message"]["content"]
        if content is None:
            # Thinking models emit content=None when the completion budget dies
            # in reasoning; surface the finish reason instead of an AttributeError.
            reason = data["choices"][0].get("finish_reason")
            raise LLMError(f"LLM returned no content (finish_reason={reason})")
        return LLMResponse(
            content=content,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
        )
