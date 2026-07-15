"""LLM provider abstraction (see docs/ARCHITECTURE.md, LlmProvider ABC).

`complete_json` is implemented once in the base class: it embeds the schema
hint, calls the provider's raw completion, and parses/repairs the reply into a
dict. One retry (with an explicit repair instruction) — then `ProviderError`.
Network/HTTP failures count as failed attempts and follow the same retry path.
"""
from __future__ import annotations

import copy
import json
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from src import config


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a valid JSON object after retry."""


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of an LLM reply.

    Handles code fences and surrounding prose by slicing from the first '{'
    to the last '}'. Falls back to a trailing-comma repair before giving up.
    Raises ValueError if no JSON object can be recovered.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line and any closing fence.
        lines = stripped.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines)

    starts = [match.start() for match in re.finditer(r"\{", stripped)]
    if not starts:
        raise ValueError("no JSON object found in reply")

    decoder = json.JSONDecoder()
    errors: list[str] = []
    for start in starts:
        try:
            obj, _ = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if isinstance(obj, dict):
            return obj

    # Common LLM slip: trailing commas before a closing bracket/brace.
    start, end = stripped.find("{"), stripped.rfind("}")
    candidate = stripped[start:end + 1]
    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        obj = json.loads(repaired)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reply is not valid JSON: {errors[-1] if errors else exc}") from exc
    if isinstance(obj, dict):
        return obj
    raise ValueError("reply parsed to non-object JSON")


class LlmProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def _complete_text(self, system: str, user: str, max_tokens: int) -> str:
        """Return the raw assistant text for one system+user exchange."""

    def complete_json(self, system: str, user: str, schema_hint: str,
                      max_tokens: int = 4096) -> dict[str, Any]:
        full_system = (
            f"{system}\n\n"
            "Respond with a single JSON object and nothing else — no prose, "
            "no code fences. The object must match this schema:\n"
            f"{schema_hint}"
        )
        prompt = user
        last_error = ""
        for _attempt in range(2):
            try:
                raw = self._complete_text(full_system, prompt, max_tokens)
            except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError,
                    TypeError, ValueError) as exc:
                last_error = f"request failed: {exc}"
                continue
            try:
                return extract_json(raw)
            except ValueError as exc:
                last_error = str(exc)
                prompt = (
                    f"{user}\n\n"
                    "IMPORTANT: your previous reply could not be parsed as JSON "
                    f"({exc}). Reply again with ONLY a valid JSON object matching "
                    "the schema in the system prompt."
                )
        raise ProviderError(f"{self.name}: no valid JSON after retry — {last_error}")


class GroqProvider(LlmProvider):
    """Groq's OpenAI-compatible chat completions endpoint, JSON mode."""

    name = "groq"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.model = model or config.GROQ_MODEL
        self._client = httpx.Client(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {api_key or config.GROQ_API_KEY}"},
            timeout=60.0,
            transport=transport,
        )

    def _complete_text(self, system: str, user: str, max_tokens: int) -> str:
        resp = self._client.post("/chat/completions", json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        })
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class OllamaProvider(LlmProvider):
    """Local Ollama via its OpenAI-compatible endpoint (/v1)."""

    name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.model = model or config.OLLAMA_MODEL
        root = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        if root.endswith("/v1"):
            root = root[:-3]
        self._client = httpx.Client(
            base_url=f"{root}/v1",
            timeout=120.0,  # local models are slow; generous budget
            transport=transport,
        )

    def _complete_text(self, system: str, user: str, max_tokens: int) -> str:
        resp = self._client.post("/chat/completions", json={
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        })
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class AnthropicProvider(LlmProvider):
    """Anthropic Messages API. No JSON mode — relies on prompt + extraction."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.model = model or config.ANTHROPIC_MODEL
        self._client = httpx.Client(
            base_url="https://api.anthropic.com",
            headers={
                "x-api-key": api_key or config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            timeout=60.0,
            transport=transport,
        )

    def _complete_text(self, system: str, user: str, max_tokens: int) -> str:
        resp = self._client.post("/v1/messages", json={
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        })
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


class MockProvider(LlmProvider):
    """Replays canned dicts in order; raises ProviderError when exhausted.

    Records every call in `self.calls` so tests can assert on prompt content.
    Responses are deep-copied so canned fixtures are never mutated downstream.
    """

    name = "mock"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def _complete_text(self, system: str, user: str, max_tokens: int) -> str:
        raise AssertionError("MockProvider serves complete_json directly")

    def complete_json(self, system: str, user: str, schema_hint: str,
                      max_tokens: int = 4096) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user,
                           "schema_hint": schema_hint, "max_tokens": max_tokens})
        if not self._responses:
            raise ProviderError("mock: canned responses exhausted")
        return copy.deepcopy(self._responses.pop(0))


def get_provider(name: str | None = None) -> LlmProvider:
    """Factory: build the provider selected by REQPILOT_PROVIDER (or `name`)."""
    chosen = (name or config.PROVIDER).strip().lower()
    if chosen == "groq":
        return GroqProvider()
    if chosen == "anthropic":
        return AnthropicProvider()
    if chosen == "ollama":
        return OllamaProvider()
    if chosen == "mock":
        return MockProvider([])
    raise ValueError(f"unknown provider {chosen!r} (expected groq|anthropic|ollama|mock)")
