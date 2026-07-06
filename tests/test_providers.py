from __future__ import annotations

import json

import httpx
import pytest

from mycode.providers.anthropic import AnthropicProvider
from mycode.providers.deepseek import DeepSeekProvider
from mycode.providers.factory import create_provider
from mycode.providers.openai import OpenAIProvider
from mycode.types import AppConfig, ConfigError, Message, StreamEvent, ThinkingConfig, TokenUsage, ToolCall, ToolSpec


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


def test_openai_provider_builds_tool_messages_and_tools() -> None:
    provider = OpenAIProvider(config("openai"))
    tool = ToolSpec(name="read_file", description="Read", parameters={"type": "object"})
    message = Message(
        role="assistant",
        content="",
        tool_calls=(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}),),
    )

    assert provider._convert_message(message)["tool_calls"][0]["function"]["name"] == "read_file"
    assert provider._convert_message(Message(role="tool", content="{}", tool_call_id="1"))["role"] == "tool"


def test_openai_provider_parses_tool_call_stream() -> None:
    provider = OpenAIProvider(config("openai"))
    response = FakeSseResponse([
        "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "1", "function": {"name": "read_file", "arguments": "{\"path\""}}]}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ": \"a.txt\"}"}}]}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ])

    events = list(provider._iter_events(response))

    assert events[0].type == "tool_call_delta"
    assert events[1].arguments_delta == ': "a.txt"}'
    assert events[2] == StreamEvent(type="tool_call_done", tool_call_id="1", tool_name="read_file")


def test_openai_provider_parses_token_usage() -> None:
    provider = OpenAIProvider(config("openai"))
    response = FakeSseResponse([
        "data: "
        + json.dumps(
            {
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }
        ),
        "data: [DONE]",
    ])

    assert list(provider._iter_events(response)) == [
        StreamEvent(type="token_usage", token_usage=TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3)),
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


def test_anthropic_provider_builds_tool_messages_and_tools() -> None:
    provider = AnthropicProvider(config("anthropic"))
    tool = ToolSpec(name="read_file", description="Read", parameters={"type": "object"})
    payload = provider._build_payload([Message(role="user", content="hi")], [tool])
    assistant = provider._convert_message(
        Message(role="assistant", content="", tool_calls=(ToolCall(id="1", name="read_file", arguments={}),))
    )
    tool_result = provider._convert_message(Message(role="tool", content="{}", tool_call_id="1"))

    assert payload["tools"][0]["input_schema"] == {"type": "object"}
    assert assistant["content"][0]["type"] == "tool_use"
    assert tool_result["content"][0]["type"] == "tool_result"


def test_anthropic_provider_parses_tool_call_stream() -> None:
    provider = AnthropicProvider(config("anthropic"))
    response = FakeSseResponse([
        "data: " + json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "1", "name": "read_file"}}),
        "data: " + json.dumps({"type": "content_block_delta", "index": 0, "delta": {"partial_json": "{\"path\": \"a.txt\"}"}}),
        "data: " + json.dumps({"type": "content_block_stop", "index": 0}),
        "data: " + json.dumps({"type": "message_stop"}),
    ])

    events = list(provider._iter_events(response))

    assert events[0] == StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file")
    assert events[1].arguments_delta == '{"path": "a.txt"}'
    assert events[2] == StreamEvent(type="tool_call_done", tool_call_id="1", tool_name="read_file")


def test_anthropic_provider_parses_token_usage() -> None:
    provider = AnthropicProvider(config("anthropic"))
    response = FakeSseResponse([
        "data: " + json.dumps({"type": "message_delta", "usage": {"input_tokens": 4, "output_tokens": 5}}),
        "data: " + json.dumps({"type": "message_stop"}),
    ])

    assert list(provider._iter_events(response)) == [
        StreamEvent(type="token_usage", token_usage=TokenUsage(input_tokens=4, output_tokens=5, total_tokens=9)),
        StreamEvent(type="message_done"),
    ]


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
