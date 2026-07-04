from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from mycode.providers.sse import iter_sse_data_lines
from mycode.types import AppConfig, Message, ProviderError, StreamEvent


DEFAULT_MAX_TOKENS = 4096
DEFAULT_THINKING_BUDGET_TOKENS = 4096
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def stream_chat(self, messages: Sequence[Message]) -> Iterator[StreamEvent]:
        payload = self._build_payload(messages)
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

    def _build_payload(self, messages: Sequence[Message]) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "max_tokens": DEFAULT_MAX_TOKENS,
            "stream": True,
        }

        thinking = self.config.thinking
        if thinking and thinking.enabled:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking.budget_tokens or DEFAULT_THINKING_BUDGET_TOKENS,
            }

        return payload

    def _iter_events(self, response: httpx.Response) -> Iterator[StreamEvent]:
        for data in iter_sse_data_lines(response):
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError("Claude API 返回了无法解析的流式数据。") from exc

            event_type = event.get("type")
            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                text = delta.get("text")
                if text:
                    yield StreamEvent(type="text_delta", text=text)
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
