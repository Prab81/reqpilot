from __future__ import annotations

import json

import httpx
import pytest

from src.intelligence.providers import (
    AnthropicProvider,
    GroqProvider,
    LlmProvider,
    OllamaProvider,
    ProviderError,
    extract_json,
    get_provider,
)


class ScriptedProvider(LlmProvider):
    name = "scripted"

    def __init__(self, replies: list[object]) -> None:
        self.replies = list(replies)
        self.users: list[str] = []

    def _complete_text(self, system: str, user: str, max_tokens: int) -> str:
        self.users.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return str(reply)


@pytest.mark.parametrize(("reply", "expected"), [
    ('```json\n{"ok": true}\n```', {"ok": True}),
    ('Here is a brace {not json}; result: {"ok": 2}', {"ok": 2}),
    ('{"items": [1, 2,],}', {"items": [1, 2]}),
])
def test_extract_json_repairs_common_provider_output(reply: str, expected: dict) -> None:
    assert extract_json(reply) == expected


def test_complete_json_retries_once_with_repair_instruction() -> None:
    provider = ScriptedProvider(["not json", '{"fixed": true}'])
    assert provider.complete_json("system", "user", "{}") == {"fixed": True}
    assert len(provider.users) == 2
    assert "previous reply could not be parsed" in provider.users[1]


def test_complete_json_raises_after_two_failures() -> None:
    provider = ScriptedProvider(["bad", "still bad"])
    with pytest.raises(ProviderError, match="after retry"):
        provider.complete_json("system", "user", "{}")


@pytest.mark.parametrize("provider_kind", ["groq", "anthropic", "ollama"])
def test_http_providers_use_expected_protocol_without_network(provider_kind: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if provider_kind == "anthropic":
            return httpx.Response(200, json={"content": [{"type": "text", "text": '{"ok":true}'}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    transport = httpx.MockTransport(handler)
    if provider_kind == "groq":
        provider = GroqProvider(api_key="test", model="model", transport=transport)
    elif provider_kind == "anthropic":
        provider = AnthropicProvider(api_key="test", model="model", transport=transport)
    else:
        provider = OllamaProvider(base_url="http://ollama.test/v1", model="model", transport=transport)

    assert provider.complete_json("system", "user", "{}") == {"ok": True}
    body = json.loads(requests[0].content)
    assert body["model"] == "model"
    assert body["messages"][-1]["content"] == "user"
    assert requests[0].url.path == ("/v1/messages" if provider_kind == "anthropic"
                                    else "/openai/v1/chat/completions" if provider_kind == "groq"
                                    else "/v1/chat/completions")


def test_http_failure_is_retried_then_wrapped() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(503, text="down"))
    provider = GroqProvider(api_key="test", transport=transport)
    with pytest.raises(ProviderError, match="503"):
        provider.complete_json("system", "user", "{}")


def test_provider_factory_rejects_unknown_name() -> None:
    assert get_provider("mock").name == "mock"
    with pytest.raises(ValueError, match="unknown provider"):
        get_provider("other")

