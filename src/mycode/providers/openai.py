from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from mycode.providers.sse import iter_sse_data_lines
from mycode.types import AppConfig, Message, ProviderError, StreamEvent, ToolCall, ToolSpec


class OpenAIProvider:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> Iterator[StreamEvent]:
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [self._convert_message(message) for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = [_openai_tool(tool) for tool in tools]
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url}/chat/completions"

        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("POST", url, headers=headers, json=payload) as response:
                    _raise_for_status(response)
                    yield from self._iter_events(response)
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError("调用模型 API 时发生网络错误。") from exc

    def _convert_message(self, message: Message) -> dict[str, object]:
        if message.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            }
        converted: dict[str, object] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            converted["tool_calls"] = [_openai_tool_call(call) for call in message.tool_calls]
        return converted

    def _iter_events(self, response: httpx.Response) -> Iterator[StreamEvent]:
        tool_ids_by_index: dict[int, str] = {}
        tool_names_by_index: dict[int, str] = {}
        for data in iter_sse_data_lines(response):
            if data == "[DONE]":
                yield StreamEvent(type="message_done")
                return

            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError("模型 API 返回了无法解析的流式数据。") from exc

            choice = event.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            text_delta = delta.get("content")
            if text_delta:
                yield StreamEvent(type="text_delta", text=text_delta)

            for tool_call in delta.get("tool_calls", []) or []:
                index = int(tool_call.get("index", 0))
                tool_call_id = tool_call.get("id") or tool_ids_by_index.get(index, "")
                function = tool_call.get("function", {}) or {}
                tool_name = function.get("name") or tool_names_by_index.get(index, "")
                arguments_delta = function.get("arguments") or ""
                if tool_call_id:
                    tool_ids_by_index[index] = str(tool_call_id)
                if tool_name:
                    tool_names_by_index[index] = str(tool_name)
                yield StreamEvent(
                    type="tool_call_delta",
                    tool_call_id=str(tool_call_id),
                    tool_name=str(tool_name),
                    arguments_delta=str(arguments_delta),
                )

            if choice.get("finish_reason") == "tool_calls":
                for index, tool_call_id in sorted(tool_ids_by_index.items()):
                    yield StreamEvent(
                        type="tool_call_done",
                        tool_call_id=tool_call_id,
                        tool_name=tool_names_by_index.get(index, ""),
                    )


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise ProviderError(f"模型 API 请求失败，HTTP 状态码：{status}") from exc


def _openai_tool(spec: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _openai_tool_call(call: ToolCall) -> dict[str, object]:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.arguments, ensure_ascii=False),
        },
    }
