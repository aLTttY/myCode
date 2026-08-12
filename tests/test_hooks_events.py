import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mycode.context.models import CompactionReport
from mycode.hooks.events import HookEventFactory
from mycode.hooks.models import HOOK_EVENT_NAMES, HookTurn
from mycode.types import ToolCall, ToolExecutionResult, ToolResult


NOW = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)


def factory(tmp_path: Path) -> HookEventFactory:
    result = HookEventFactory(tmp_path, clock=lambda: NOW)
    result.set_session("session-1", "new")
    result.set_turn(HookTurn(1, "default", "message"))
    return result


def test_all_event_names_build_with_common_payload(tmp_path: Path) -> None:
    built = []
    for name in sorted(HOOK_EVENT_NAMES):
        built.append(factory(tmp_path).build(name))  # type: ignore[arg-type]

    assert {event.name for event in built} == HOOK_EVENT_NAMES
    for event in built:
        assert event.payload["schema_version"] == 1
        assert event.payload["workspace"] == str(tmp_path.resolve())
        assert event.payload["occurred_at"] == NOW.astimezone().isoformat(timespec="microseconds")
        json.dumps(event.payload, ensure_ascii=False)


def test_message_tool_context_and_error_payloads(tmp_path: Path) -> None:
    events = factory(tmp_path)
    message = events.build(
        "message_received", message_role="user", message_content="hello"
    )
    call = ToolCall("call-1", "run_command", {"command": "echo ok"})
    complete = ToolResult(True, "complete-secret", {"content": "x" * 100})
    display = ToolResult(True, "shown", {"content": "short"})
    tool = events.build(
        "tool_after",
        tool_call=call,
        tool_result=ToolExecutionResult(display=display, complete=complete),
        result_source="tool",
    )
    context = events.build(
        "context_compacted",
        context_report=CompactionReport("success", "automatic", 100, 50, 80),
    )
    error = events.build("agent_error", error_code="stream_error", error_message="safe")

    assert message.payload["message"] == {"role": "user", "content": "hello"}
    assert tool.payload["result"] == {
        "ok": True,
        "message": "shown",
        "data": {"content": "short"},
        "source": "tool",
    }
    assert "complete-secret" not in json.dumps(tool.payload)
    assert context.payload["context"]["before_tokens"] == 100
    assert error.payload["error"] == {"code": "stream_error", "message": "safe"}


def test_payload_is_deeply_immutable(tmp_path: Path) -> None:
    event = factory(tmp_path).build(
        "tool_before", tool_call=ToolCall("1", "run_command", {"nested": {"x": 1}})
    )

    with pytest.raises(TypeError):
        event.payload["event"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        event.payload["tool"]["arguments"]["nested"]["x"] = 2  # type: ignore[index]


def test_session_and_turn_specific_fields(tmp_path: Path) -> None:
    events = factory(tmp_path)
    session_end = events.build("session_end", end_reason="exit")
    turn_end = events.build("turn_end", stop_reason="completed")

    assert "turn" not in session_end.payload
    assert session_end.payload["session"]["end_reason"] == "exit"
    assert turn_end.payload["turn"]["stop_reason"] == "completed"
