from __future__ import annotations

from mycode.agent.collector import CollectedResponse, StreamCollector
from mycode.agent.events import AgentEvent
from mycode.types import StreamEvent, TokenUsage, ToolCall


def collect(events: list[StreamEvent]) -> list[AgentEvent | CollectedResponse]:
    return list(StreamCollector().collect(events))


def test_collector_streams_text_and_collects_full_response() -> None:
    events = collect([
        StreamEvent(type="text_delta", text="你"),
        StreamEvent(type="text_delta", text="好"),
        StreamEvent(type="message_done"),
    ])

    assert events[0] == AgentEvent(type="text_delta", text="你")
    assert events[1] == AgentEvent(type="text_delta", text="好")
    assert events[-1] == CollectedResponse(assistant_text="你好", tool_calls=(), parse_errors=())


def test_collector_collects_single_tool_call() -> None:
    events = collect([
        StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path"'),
        StreamEvent(type="tool_call_delta", tool_call_id="1", arguments_delta=': "a.txt"}'),
        StreamEvent(type="tool_call_done", tool_call_id="1"),
        StreamEvent(type="message_done"),
    ])

    assert events[-1].tool_calls == (ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}),)


def test_collector_collects_multiple_tool_calls() -> None:
    events = collect([
        StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path": "a.txt"}'),
        StreamEvent(type="tool_call_done", tool_call_id="1"),
        StreamEvent(type="tool_call_delta", tool_call_id="2", tool_name="find_files", arguments_delta='{"pattern": "*.py"}'),
        StreamEvent(type="tool_call_done", tool_call_id="2"),
        StreamEvent(type="message_done"),
    ])

    assert [call.id for call in events[-1].tool_calls] == ["1", "2"]


def test_collector_reports_invalid_json() -> None:
    events = collect([
        StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta="{bad"),
        StreamEvent(type="tool_call_done", tool_call_id="1"),
        StreamEvent(type="message_done"),
    ])

    assert events[-1].parse_errors
    assert "合法 JSON" in events[-1].parse_errors[0].message


def test_collector_forwards_token_usage() -> None:
    usage = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3)
    events = collect([StreamEvent(type="token_usage", token_usage=usage), StreamEvent(type="message_done")])

    assert events[0] == AgentEvent(type="token_usage", token_usage=usage)
    assert events[-1].token_usage == usage
