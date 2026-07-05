from collections.abc import Iterator, Sequence
from pathlib import Path

from mycode.session import ChatSession
from mycode.tools.registry import create_default_registry
from mycode.types import Message, StreamEvent, ToolContext, ToolSpec


class ToolCallProvider:
    def __init__(self, events: list[StreamEvent]) -> None:
        self.events = events
        self.calls: list[tuple[tuple[Message, ...], tuple[ToolSpec, ...]]] = []

    def stream_chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
    ) -> Iterator[StreamEvent]:
        self.calls.append((tuple(messages), tuple(tools)))
        if len(self.calls) == 1:
            yield from self.events
        else:
            yield StreamEvent(type="text_delta", text="done")
            yield StreamEvent(type="message_done")


def session(provider: ToolCallProvider, tmp_path: Path) -> ChatSession:
    return ChatSession(provider, create_default_registry(), ToolContext(workspace_root=tmp_path))


def test_single_tool_call_json_fragments(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ToolCallProvider([
        StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path"'),
        StreamEvent(type="tool_call_delta", tool_call_id="1", arguments_delta=': "a.txt"}'),
        StreamEvent(type="tool_call_done", tool_call_id="1"),
        StreamEvent(type="message_done"),
    ])

    list(session(provider, tmp_path).send("read"))

    assert provider.calls[1][0][-1].role == "tool"
    assert "hello" in provider.calls[1][0][-1].content


def test_multiple_tool_calls_keep_order(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    provider = ToolCallProvider([
        StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path": "a.txt"}'),
        StreamEvent(type="tool_call_done", tool_call_id="1"),
        StreamEvent(type="tool_call_delta", tool_call_id="2", tool_name="read_file", arguments_delta='{"path": "b.txt"}'),
        StreamEvent(type="tool_call_done", tool_call_id="2"),
        StreamEvent(type="message_done"),
    ])

    list(session(provider, tmp_path).send("read both"))

    tool_messages = [message for message in provider.calls[1][0] if message.role == "tool"]
    assert [message.tool_call_id for message in tool_messages] == ["1", "2"]


def test_invalid_json_becomes_tool_result(tmp_path: Path) -> None:
    provider = ToolCallProvider([
        StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta="{bad"),
        StreamEvent(type="tool_call_done", tool_call_id="1"),
        StreamEvent(type="message_done"),
    ])

    list(session(provider, tmp_path).send("bad"))

    assert "合法 JSON" in provider.calls[1][0][-1].content
