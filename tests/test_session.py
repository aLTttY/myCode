from collections.abc import Iterator, Sequence

import pytest

from mycode.session import ChatSession
from mycode.types import Message, ProviderError, StreamEvent


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[Message, ...]] = []

    def stream_chat(self, messages: Sequence[Message]) -> Iterator[StreamEvent]:
        self.calls.append(tuple(messages))
        yield StreamEvent(type="text_delta", text="你好")
        yield StreamEvent(type="text_delta", text="！")
        yield StreamEvent(type="message_done")


class BrokenProvider:
    def stream_chat(self, messages: Sequence[Message]) -> Iterator[StreamEvent]:
        raise ProviderError("失败")
        yield StreamEvent(type="message_done")


def test_session_appends_user_and_assistant_messages() -> None:
    provider = FakeProvider()
    session = ChatSession(provider)

    events = list(session.send("你好"))

    assert events == [
        StreamEvent(type="text_delta", text="你好"),
        StreamEvent(type="text_delta", text="！"),
        StreamEvent(type="message_done"),
    ]
    assert session.messages == [
        Message(role="user", content="你好"),
        Message(role="assistant", content="你好！"),
    ]


def test_session_sends_full_history_on_next_turn() -> None:
    provider = FakeProvider()
    session = ChatSession(provider)

    list(session.send("第一轮"))
    list(session.send("第二轮"))

    assert provider.calls[1] == (
        Message(role="user", content="第一轮"),
        Message(role="assistant", content="你好！"),
        Message(role="user", content="第二轮"),
    )


def test_session_does_not_append_empty_assistant_on_error() -> None:
    session = ChatSession(BrokenProvider())

    with pytest.raises(ProviderError):
        list(session.send("会失败"))

    assert session.messages == [Message(role="user", content="会失败")]
