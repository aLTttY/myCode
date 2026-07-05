from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from mycode.providers.sse import iter_sse_data_lines
from mycode.types import AppConfig, Message, ProviderError, StreamEvent, ToolCall, ToolSpec


DEFAULT_MAX_TOKENS = 4096
DEFAULT_THINKING_BUDGET_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> Iterator[StreamEvent]:
        payload = self._build_payload(messages, tools)
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
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [self._convert_message(message) for message in messages],
            "max_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if tools:
            payload["tools"] = [_anthropic_tool(tool) for tool in tools]

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


def _anthropic_tool(spec: ToolSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters,
    }


def _anthropic_tool_call(call: ToolCall) -> dict[str, object]:
    return {
        "type": "tool_use",
        "id": call.id,
        "name": call.name,
        "input": call.arguments,
    }
