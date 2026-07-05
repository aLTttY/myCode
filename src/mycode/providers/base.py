from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Protocol

from mycode.types import Message, StreamEvent, ToolSpec


class LLMProvider(Protocol):
    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> Iterator[StreamEvent]:
        ...
