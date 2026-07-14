from collections.abc import Iterator
from pathlib import Path

from mycode.providers.base import ChatRequest
from mycode.session import ChatSession
from mycode.tools.registry import create_default_registry
from mycode.types import Message, StreamEvent, ToolContext


class ScriptedProvider:
    def __init__(self, first: list[StreamEvent], second: list[StreamEvent]) -> None:
        self.first = first
        self.second = second
        self.calls: list[ChatRequest] = []

    def stream_chat(
        self,
        request: ChatRequest,
    ) -> Iterator[StreamEvent]:
        self.calls.append(request)
        yield from (self.first if len(self.calls) == 1 else self.second)


def make_session(provider: ScriptedProvider, tmp_path: Path) -> ChatSession:
    return ChatSession(provider, create_default_registry(), ToolContext(workspace_root=tmp_path))


def test_tool_success_followup_appends_history(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ScriptedProvider(
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path": "a.txt"}'),
            StreamEvent(type="tool_call_done", tool_call_id="1"),
            StreamEvent(type="message_done"),
        ],
        [StreamEvent(type="text_delta", text="read ok"), StreamEvent(type="message_done")],
    )
    session = make_session(provider, tmp_path)

    events = list(session.send("read file"))

    assert any(event.type == "tool_started" for event in events)
    assert any(event.type == "tool_finished" and event.tool_result and event.tool_result.ok for event in events)
    assert len(provider.calls) == 2
    assert provider.calls[0].tools
    assert provider.calls[1].tools == ()
    assert [message.role for message in session.messages] == ["user", "assistant", "tool", "assistant"]


def test_tool_failure_is_fed_back(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path": "missing.txt"}'),
            StreamEvent(type="tool_call_done", tool_call_id="1"),
            StreamEvent(type="message_done"),
        ],
        [StreamEvent(type="text_delta", text="missing"), StreamEvent(type="message_done")],
    )

    list(make_session(provider, tmp_path).send("read missing"))

    assert "文件不存在" in provider.calls[1].messages[-1].content


def test_unknown_tool_is_fed_back(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="missing", arguments_delta="{}"),
            StreamEvent(type="tool_call_done", tool_call_id="1"),
            StreamEvent(type="message_done"),
        ],
        [StreamEvent(type="text_delta", text="unknown"), StreamEvent(type="message_done")],
    )

    list(make_session(provider, tmp_path).send("unknown"))

    assert "未知工具" in provider.calls[1].messages[-1].content


def test_followup_tool_call_is_not_executed_again(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="find_files", arguments_delta='{"pattern": "*.py"}'),
            StreamEvent(type="tool_call_done", tool_call_id="1"),
            StreamEvent(type="message_done"),
        ],
        [
            StreamEvent(type="tool_call_delta", tool_call_id="2", tool_name="run_command", arguments_delta='{"command": "echo bad"}'),
            StreamEvent(type="tool_call_done", tool_call_id="2"),
            StreamEvent(type="message_done"),
        ],
    )

    events = list(make_session(provider, tmp_path).send("loop?"))

    assert sum(1 for event in events if event.type == "tool_finished") == 1
    assert any("不会继续执行" in event.text for event in events if event.type == "text_delta")


def test_plain_chat_still_streams(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [StreamEvent(type="text_delta", text="hi"), StreamEvent(type="message_done")],
        [],
    )
    session = make_session(provider, tmp_path)

    events = list(session.send("hello"))

    assert events == [StreamEvent(type="text_delta", text="hi"), StreamEvent(type="message_done")]
    assert session.messages[-1] == Message(role="assistant", content="hi")
