from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from mycode.prompts.modes import DynamicInstruction
from mycode.types import Message, StreamEvent, ToolSpec


@dataclass(frozen=True)
class ChatRequest:
    stable_system_prompt: str
    dynamic_system_messages: tuple[DynamicInstruction, ...]
    messages: tuple[Message, ...]
    optional_system_prompt: str = ""
    tools: tuple[ToolSpec, ...] = ()
    cache_static_content: bool = True


def plain_chat_request(
    messages: Sequence[Message],
    tools: Sequence[ToolSpec] = (),
) -> ChatRequest:
    return ChatRequest(
        stable_system_prompt="",
        dynamic_system_messages=(),
        messages=tuple(messages),
        tools=tuple(tools),
        cache_static_content=False,
    )


class LLMProvider(Protocol):
    def stream_chat(
        self,
        request: ChatRequest,
    ) -> Iterator[StreamEvent]:
        ...
