from __future__ import annotations

import json

import httpx
import pytest

from mycode.providers.anthropic import AnthropicProvider
from mycode.providers.deepseek import DeepSeekProvider
from mycode.providers.factory import create_provider
from mycode.providers.openai import OpenAIProvider
from mycode.types import AppConfig, ConfigError, Message, StreamEvent, ThinkingConfig


def config(protocol: str) -> AppConfig:
    return AppConfig(
        protocol=protocol,
        model="demo",
        base_url="https://example.com",
        api_key="key",
    )


def test_factory_rejects_unknown_protocol() -> None:
    try:
        create_provider(config("unknown"))
    except ConfigError as exc:
        assert "不支持" in exc.user_message
    else:
        raise AssertionError("expected ConfigError")


def test_factory_creates_openai_provider() -> None:
    assert isinstance(create_provider(config("openai")), OpenAIProvider)


def test_factory_creates_anthropic_provider() -> None:
    assert isinstance(create_provider(config("anthropic")), AnthropicProvider)


def test_factory_creates_deepseek_provider() -> None:
    assert isinstance(create_provider(config("deepseek")), DeepSeekProvider)


class FakeSseResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://example.com")

    def iter_lines(self):
        yield from self._lines

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request)
            raise httpx.HTTPStatusError("bad status", request=self.request, response=response)


def openai_line(content: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": content}}]})


def anthropic_line(event_type: str, text: str | None = None) -> str:
    event: dict[str, object] = {"type": event_type}
    if text is not None:
        event["delta"] = {"text": text}
    return "data: " + json.dumps(event)


def test_openai_provider_converts_stream_events() -> None:
    provider = OpenAIProvider(config("openai"))
    response = FakeSseResponse([openai_line("你"), openai_line("好"), "data: [DONE]"])

    assert list(provider._iter_events(response)) == [
        StreamEvent(type="text_delta", text="你"),
        StreamEvent(type="text_delta", text="好"),
        StreamEvent(type="message_done"),
    ]


def test_deepseek_provider_reuses_openai_stream_events() -> None:
    provider = DeepSeekProvider(config("deepseek"))
    response = FakeSseResponse([openai_line("DeepSeek"), "data: [DONE]"])

    assert list(provider._iter_events(response)) == [
        StreamEvent(type="text_delta", text="DeepSeek"),
        StreamEvent(type="message_done"),
    ]


def test_openai_provider_wraps_bad_json() -> None:
    provider = OpenAIProvider(config("openai"))
    response = FakeSseResponse(["data: not-json"])

    with pytest.raises(Exception, match="无法解析"):
        list(provider._iter_events(response))


def test_anthropic_provider_converts_stream_events() -> None:
    provider = AnthropicProvider(config("anthropic"))
    response = FakeSseResponse([
        anthropic_line("content_block_delta", "你"),
        anthropic_line("content_block_delta", "好"),
        anthropic_line("message_stop"),
    ])

    assert list(provider._iter_events(response)) == [
        StreamEvent(type="text_delta", text="你"),
        StreamEvent(type="text_delta", text="好"),
        StreamEvent(type="message_done"),
    ]


def test_anthropic_provider_includes_thinking_when_enabled() -> None:
    provider = AnthropicProvider(
        AppConfig(
            protocol="anthropic",
            model="claude-demo",
            base_url="https://example.com",
            api_key="key",
            thinking=ThinkingConfig(enabled=True, budget_tokens=2048),
        )
    )

    payload = provider._build_payload([Message(role="user", content="hi")])

    assert payload["thinking"] == {"type": "enabled", "budget_tokens": 2048}


def test_anthropic_provider_omits_thinking_when_disabled() -> None:
    provider = AnthropicProvider(
        AppConfig(
            protocol="anthropic",
            model="claude-demo",
            base_url="https://example.com",
            api_key="key",
            thinking=ThinkingConfig(enabled=False, budget_tokens=2048),
        )
    )

    payload = provider._build_payload([Message(role="user", content="hi")])

    assert "thinking" not in payload
