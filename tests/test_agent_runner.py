from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from mycode.agent.cancellation import CancellationToken
from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.tools.registry import create_default_registry
from mycode.types import ProviderError, StreamEvent, ToolContext


class ScriptedProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[ChatRequest] = []

    def stream_chat(
        self,
        request: ChatRequest,
    ) -> Iterator[StreamEvent]:
        self.calls.append(request)
        script = self.scripts[min(len(self.calls) - 1, len(self.scripts) - 1)]
        yield from script


class BrokenProvider:
    def stream_chat(
        self,
        request: ChatRequest,
    ) -> Iterator[StreamEvent]:
        raise ProviderError("stream broke")
        yield StreamEvent(type="message_done")


def runner(provider: LLMProvider, tmp_path: Path, config: AgentConfig = AgentConfig()) -> AgentRunner:
    return AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        config,
        PermissionService.with_mode("allow"),
    )


def tool_call_events(tool_call_id: str, name: str, arguments_json: str) -> list[StreamEvent]:
    return [
        StreamEvent(type="tool_call_delta", tool_call_id=tool_call_id, tool_name=name, arguments_delta=arguments_json),
        StreamEvent(type="tool_call_done", tool_call_id=tool_call_id),
        StreamEvent(type="message_done"),
    ]


def test_agent_runner_completed_after_multiple_iterations(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ScriptedProvider([
        tool_call_events("1", "read_file", '{"path": "a.txt"}'),
        [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")],
    ])

    events = list(runner(provider, tmp_path).run(AgentRequest("read it")))

    assert [event.stop_reason for event in events if event.type == "done"] == ["completed"]
    assert len(provider.calls) == 2
    assert provider.calls[1].messages[-1].role == "tool"


def test_permission_denial_is_fed_back_and_loop_continues(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ScriptedProvider([
        tool_call_events("1", "read_file", '{"path": "a.txt"}'),
        [StreamEvent(type="text_delta", text="used another approach"), StreamEvent(type="message_done")],
    ])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("default"),
    )

    events = list(agent.run(AgentRequest("read it")))

    assert events[-1].stop_reason == "completed"
    assert len(provider.calls) == 2
    assert "user_denied" in provider.calls[1].messages[-1].content


def test_agent_runner_writes_each_tool_result_to_history(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    provider = ScriptedProvider([
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta='{"path": "a.txt"}'),
            StreamEvent(type="tool_call_done", tool_call_id="1"),
            StreamEvent(type="tool_call_delta", tool_call_id="2", tool_name="read_file", arguments_delta='{"path": "b.txt"}'),
            StreamEvent(type="tool_call_done", tool_call_id="2"),
            StreamEvent(type="message_done"),
        ],
        [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")],
    ])

    list(runner(provider, tmp_path).run(AgentRequest("read both")))

    tool_messages = [message for message in provider.calls[1].messages if message.role == "tool"]
    assert {message.tool_call_id for message in tool_messages} == {"1", "2"}


def test_agent_runner_emits_progress_and_plain_chat(tmp_path: Path) -> None:
    provider = ScriptedProvider([[StreamEvent(type="text_delta", text="hi"), StreamEvent(type="message_done")]])

    events = list(runner(provider, tmp_path).run(AgentRequest("hello")))

    assert any(event.type == "progress" and event.iteration == 1 for event in events)
    assert any(event.type == "text_delta" and event.text == "hi" for event in events)
    assert events[-1].stop_reason == "completed"


def test_agent_runner_stops_at_max_iterations(tmp_path: Path) -> None:
    provider = ScriptedProvider([tool_call_events("1", "find_files", '{"pattern": "*.py"}')])

    events = list(runner(provider, tmp_path, AgentConfig(max_iterations=1)).run(AgentRequest("loop")))

    assert events[-1].stop_reason == "max_iterations"


def test_agent_runner_stops_when_cancelled(tmp_path: Path) -> None:
    token = CancellationToken()
    token.cancel()
    provider = ScriptedProvider([[StreamEvent(type="text_delta", text="never"), StreamEvent(type="message_done")]])

    events = list(runner(provider, tmp_path).run(AgentRequest("cancel"), token))

    assert events[-1].stop_reason == "cancelled"
    assert provider.calls == []


def test_agent_runner_stops_after_unknown_tools(tmp_path: Path) -> None:
    provider = ScriptedProvider([
        tool_call_events("1", "missing", "{}"),
        tool_call_events("2", "missing", "{}"),
    ])

    events = list(
        runner(provider, tmp_path, AgentConfig(max_iterations=4, max_unknown_tool_calls=2)).run(AgentRequest("unknown"))
    )

    assert events[-1].stop_reason == "unknown_tools"


def test_agent_runner_stops_on_stream_error(tmp_path: Path) -> None:
    events = list(runner(BrokenProvider(), tmp_path).run(AgentRequest("broken")))

    assert any(event.type == "error" and event.stop_reason == "stream_error" for event in events)
    assert events[-1].stop_reason == "stream_error"


def test_agent_runner_stops_on_tool_parse_error(tmp_path: Path) -> None:
    provider = ScriptedProvider([
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file", arguments_delta="{bad"),
            StreamEvent(type="tool_call_done", tool_call_id="1"),
            StreamEvent(type="message_done"),
        ]
    ])

    events = list(runner(provider, tmp_path).run(AgentRequest("bad")))

    assert events[-1].stop_reason == "tool_parse_error"


def test_agent_runner_plan_mode_uses_readonly_tools(tmp_path: Path) -> None:
    provider = ScriptedProvider([[StreamEvent(type="text_delta", text="plan"), StreamEvent(type="message_done")]])

    events = list(runner(provider, tmp_path).run(AgentRequest("inspect", mode="plan")))

    assert {tool.name for tool in provider.calls[0].tools} == {"read_file", "find_files", "search_code"}
    assert provider.calls[0].messages[-1].content == "inspect"
    assert "Plan Mode" in provider.calls[0].dynamic_system_messages[1].render()
    assert any(event.type == "text_delta" and event.text == "plan" for event in events)


def test_agent_runner_do_and_default_use_full_tools(tmp_path: Path) -> None:
    provider = ScriptedProvider([
        [StreamEvent(type="text_delta", text="do"), StreamEvent(type="message_done")],
        [StreamEvent(type="text_delta", text="default"), StreamEvent(type="message_done")],
    ])
    agent = runner(provider, tmp_path)

    list(agent.run(AgentRequest("execute", mode="do")))
    list(agent.run(AgentRequest("execute", mode="default")))

    assert "write_file" in {tool.name for tool in provider.calls[0].tools}
    assert "run_command" in {tool.name for tool in provider.calls[1].tools}


def test_agent_runner_uses_structured_prompt_and_reinforced_tools(tmp_path: Path) -> None:
    provider = ScriptedProvider([[StreamEvent(type="text_delta", text="ok"), StreamEvent(type="message_done")]])

    list(runner(provider, tmp_path).run(AgentRequest("hello")))

    request = provider.calls[0]
    assert "## 身份" in request.stable_system_prompt
    assert "mewcode_environment" in request.dynamic_system_messages[0].render()
    assert "mewcode_runtime_instruction" in request.dynamic_system_messages[1].render()
    assert any("Use this tool first" in tool.description for tool in request.tools)


def test_agent_runner_repeats_full_mode_instruction_by_interval(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    provider = ScriptedProvider([
        tool_call_events("1", "read_file", '{"path": "a.txt"}'),
        tool_call_events("2", "read_file", '{"path": "a.txt"}'),
        [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")],
    ])

    list(runner(provider, tmp_path, AgentConfig(prompt_repeat_interval=3)).run(AgentRequest("read", mode="plan")))

    assert provider.calls[0].dynamic_system_messages[1].full is True
    assert provider.calls[1].dynamic_system_messages[1].full is False
    assert provider.calls[2].dynamic_system_messages[1].full is True
