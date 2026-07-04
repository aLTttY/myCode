from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from mycode.providers.sse import iter_sse_data_lines
from mycode.types import AppConfig, Message, ProviderError, StreamEvent


class OpenAIProvider:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def stream_chat(self, messages: Sequence[Message]) -> Iterator[StreamEvent]:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
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

    def _iter_events(self, response: httpx.Response) -> Iterator[StreamEvent]:
        for data in iter_sse_data_lines(response):
            if data == "[DONE]":
                yield StreamEvent(type="message_done")
                return

            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProviderError("模型 API 返回了无法解析的流式数据。") from exc

            delta = (
                event.get("choices", [{}])[0]
                .get("delta", {})
                .get("content")
            )
            if delta:
                yield StreamEvent(type="text_delta", text=delta)


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise ProviderError(f"模型 API 请求失败，HTTP 状态码：{status}") from exc
