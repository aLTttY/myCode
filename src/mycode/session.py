from __future__ import annotations

from collections.abc import Iterator

from .providers.base import LLMProvider
from .types import Message, StreamEvent


class ChatSession:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.messages: list[Message] = []

    def send(self, user_text: str) -> Iterator[StreamEvent]:
        self.messages.append(Message(role="user", content=user_text))
        assistant_parts: list[str] = []

        for event in self.provider.stream_chat(tuple(self.messages)):
            if event.type == "text_delta":
                assistant_parts.append(event.text)
                yield event
            elif event.type == "message_done":
                assistant_text = "".join(assistant_parts)
                self.messages.append(Message(role="assistant", content=assistant_text))
                yield event
