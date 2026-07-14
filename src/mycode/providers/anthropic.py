from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from mycode.providers.base import ChatRequest
from mycode.providers.sse import iter_sse_data_lines
from mycode.types import AppConfig, Message, ProviderError, StreamEvent, TokenUsage, ToolCall, ToolSpec


DEFAULT_MAX_TOKENS = 4096
DEFAULT_THINKING_BUDGET_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def stream_chat(
        self,
        request: ChatRequest,
    ) -> Iterator[StreamEvent]:
        payload = self._build_payload(request)
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        url = f"{self.config.base_url}/v1/messages"

        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("POST", url, headers=headers, json=payload) as response:
                    _raise_for_status(response)
                    yield from self._iter_events(response)
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError("调用 Claude API 时发生网络错误。") from exc

    def _build_payload(
        self,
        request: ChatRequest,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [self._convert_message(message) for message in request.messages],
            "max_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        system = _anthropic_system(request)
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [_anthropic_tool(tool, cache_control=request.cache_static_content) for tool in request.tools]

        thinking = self.config.thinking
        if thinking and thinking.enabled:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking.budget_tokens or DEFAULT_THINKING_BUDGET_TOKENS,
            }

        return payload

    def _convert_message(self, message: Message) -> dict[str, object]:
        if message.role == "tool":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": message.content,
                    }
                ],
            }
        if message.tool_calls:
            content: list[dict[str, object]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            content.extend(_anthropic_tool_call(call) for call in message.tool_calls)
            return {"role": "assistant", "content": content}
        return {"role": message.role, "content": message.content}

    def _iter_events(self, response: httpx.Response) -> Iterator[StreamEvent]:
        tool_ids_by_index: dict[int, str] = {}
        tool_names_by_index: dict[int, str] = {}
        for data in iter_sse_data_lines(response):
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError("Claude API 返回了无法解析的流式数据。") from exc

            event_type = event.get("type")
            usage = event.get("usage")
            if isinstance(usage, dict):
                yield StreamEvent(type="token_usage", token_usage=_token_usage(usage))

            if event_type == "content_block_start":
                index = int(event.get("index", 0))
                block = event.get("content_block", {}) or {}
                if block.get("type") == "tool_use":
                    tool_call_id = str(block.get("id", ""))
                    tool_name = str(block.get("name", ""))
                    tool_ids_by_index[index] = tool_call_id
                    tool_names_by_index[index] = tool_name
                    yield StreamEvent(
                        type="tool_call_delta",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )
            elif event_type == "content_block_delta":
                index = int(event.get("index", 0))
                delta = event.get("delta", {})
                text = delta.get("text")
                if text:
                    yield StreamEvent(type="text_delta", text=text)
                partial_json = delta.get("partial_json")
                if partial_json is not None:
                    yield StreamEvent(
                        type="tool_call_delta",
                        tool_call_id=tool_ids_by_index.get(index, ""),
                        tool_name=tool_names_by_index.get(index, ""),
                        arguments_delta=str(partial_json),
                    )
            elif event_type == "content_block_stop":
                index = int(event.get("index", 0))
                tool_call_id = tool_ids_by_index.get(index)
                if tool_call_id:
                    yield StreamEvent(
                        type="tool_call_done",
                        tool_call_id=tool_call_id,
                        tool_name=tool_names_by_index.get(index, ""),
                    )
            elif event_type == "message_stop":
                yield StreamEvent(type="message_done")
                return
            elif event_type == "error":
                message = event.get("error", {}).get("message", "Claude API 返回错误。")
                raise ProviderError(str(message))


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise ProviderError(f"Claude API 请求失败，HTTP 状态码：{status}") from exc


def _anthropic_system(request: ChatRequest) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    if request.stable_system_prompt:
        stable: dict[str, object] = {"type": "text", "text": request.stable_system_prompt}
        if request.cache_static_content:
            stable["cache_control"] = {"type": "ephemeral"}
        blocks.append(stable)
    dynamic_messages = list(request.dynamic_system_messages)
    if dynamic_messages:
        blocks.append({"type": "text", "text": dynamic_messages[0].render()})
        dynamic_messages = dynamic_messages[1:]
    if request.optional_system_prompt:
        blocks.append({"type": "text", "text": request.optional_system_prompt})
    blocks.extend({"type": "text", "text": instruction.render()} for instruction in dynamic_messages)
    return blocks


def _anthropic_tool(spec: ToolSpec, cache_control: bool = False) -> dict[str, object]:
    converted: dict[str, object] = {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters,
    }
    if cache_control:
        converted["cache_control"] = {"type": "ephemeral"}
    return converted


def _anthropic_tool_call(call: ToolCall) -> dict[str, object]:
    return {
        "type": "tool_use",
        "id": call.id,
        "name": call.name,
        "input": call.arguments,
    }


def _token_usage(usage: dict[str, object]) -> TokenUsage:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cache_read_tokens = usage.get("cache_read_input_tokens")
    cache_creation_tokens = usage.get("cache_creation_input_tokens")
    total_tokens = None
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    return TokenUsage(
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens if isinstance(cache_read_tokens, int) else None,
        cache_creation_tokens=cache_creation_tokens if isinstance(cache_creation_tokens, int) else None,
        cache_unavailable=not isinstance(cache_read_tokens, int) and not isinstance(cache_creation_tokens, int),
    )
