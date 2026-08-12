from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx

from mycode.agent.config import AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.hooks.actions import HookActionExecutor
from mycode.hooks.conditions import parse_condition
from mycode.hooks.config import HookConfigLoader
from mycode.hooks.events import HookEventFactory
from mycode.hooks.models import (
    AgentAction,
    CommandAction,
    HookRule,
    HookSnapshot,
    HTTPAction,
)
from mycode.hooks.runtime import HookRuntime
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest
from mycode.tools.registry import create_default_registry
from mycode.types import StreamEvent, ToolContext


class ScriptedProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.calls: list[ChatRequest] = []

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamEvent]:
        self.calls.append(request)
        yield from self.scripts[len(self.calls) - 1]


def tool_call(call_id: str, name: str, arguments: str) -> list[StreamEvent]:
    return [
        StreamEvent(
            type="tool_call_delta",
            tool_call_id=call_id,
            tool_name=name,
            arguments_delta=arguments,
        ),
        StreamEvent(type="tool_call_done", tool_call_id=call_id),
        StreamEvent(type="message_done"),
    ]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_three_layer_command_prompt_http_flow_uses_real_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write(
        home / ".mycode/hooks.yaml",
        "hooks:\n"
        "  - event: session_start\n"
        "    action: {type: command, command: 'tee session-event.json >/dev/null'}\n",
    )
    write(
        workspace / ".mycode/hooks.yaml",
        "hooks:\n"
        "  - event: turn_start\n"
        "    action: {type: prompt, content: 'project prompt', once: true}\n",
    )
    write(
        workspace / ".mycode/hooks.local.yaml",
        "hooks:\n"
        "  - event: turn_end\n"
        "    action: {type: http, url: 'https://hooks.example/turn'}\n",
    )
    snapshot = HookConfigLoader(home).load(workspace)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    actions = HookActionExecutor(
        workspace,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    hooks = HookRuntime(snapshot, HookEventFactory(workspace), actions)
    provider = ScriptedProvider(
        [[StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")]]
    )
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,
    )

    hooks.begin_session("s1", "new")
    events = list(agent.run(AgentRequest("hello")))
    hooks.end_session("exit")
    hooks.close()

    session_payload = json.loads((workspace / "session-event.json").read_text(encoding="utf-8"))
    turn_payload = json.loads(requests[0].content)
    dynamic = [item.content for item in provider.calls[0].dynamic_system_messages]
    assert [rule.source for rule in snapshot.rules] == ["user", "project", "local"]
    assert session_payload["event"] == "session_start" and session_payload["schema_version"] == 1
    assert turn_payload["event"] == "turn_end" and turn_payload["turn"]["stop_reason"] == "completed"
    assert "project prompt" in dynamic
    assert events[-1].stop_reason == "completed"
    assert all("project prompt" not in message.content for message in agent.messages)


def test_dangerous_tool_is_denied_fed_back_and_agent_recovers(tmp_path: Path) -> None:
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")
    before_condition = parse_condition(
        {
            "all": [
                "tool.name(run_command)",
                "tool.arguments.command(glob:*dangerous*)",
            ]
        },
        "tool_before",
    )
    rules = HookSnapshot(
        (
            HookRule(
                "project:1",
                "project",
                tmp_path / ".mycode/hooks.yaml",
                1,
                "tool_before",
                before_condition,
                CommandAction("printf 'blocked by policy' >&2; exit 2"),
            ),
            HookRule(
                "project:2",
                "project",
                tmp_path / ".mycode/hooks.yaml",
                2,
                "tool_after",
                None,
                HTTPAction("https://hooks.example/tools"),
            ),
        )
    )
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(204)

    actions = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    hooks = HookRuntime(rules, HookEventFactory(tmp_path), actions)
    hooks.begin_session("s1", "new")
    provider = ScriptedProvider(
        [
            tool_call("danger", "run_command", '{"command":"echo dangerous"}'),
            tool_call("safe", "read_file", '{"path":"safe.txt"}'),
            [StreamEvent(type="text_delta", text="recovered"), StreamEvent(type="message_done")],
        ]
    )
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,
    )

    events = list(agent.run(AgentRequest("try safely")))
    hooks.close()

    started = [event.tool_call_id for event in events if event.type == "tool_call_started"]
    assert started == ["safe"]
    assert "blocked by policy" in provider.calls[1].messages[-1].content
    assert events[-1].stop_reason == "completed"
    assert [(item["tool"]["call_id"], item["result"]["source"]) for item in payloads] == [
        ("danger", "hook"),
        ("safe", "tool"),
    ]


def test_multiple_hook_failures_only_emit_safe_diagnostics(tmp_path: Path) -> None:
    diagnostics = []
    snapshot = HookSnapshot(
        (
            HookRule(
                "project:1",
                "project",
                tmp_path / ".mycode/hooks.yaml",
                1,
                "turn_start",
                None,
                CommandAction("exit 9"),
            ),
            HookRule(
                "project:2",
                "project",
                tmp_path / ".mycode/hooks.yaml",
                2,
                "turn_start",
                None,
                HTTPAction("https://hooks.example/secret"),
            ),
            HookRule(
                "project:3",
                "project",
                tmp_path / ".mycode/hooks.yaml",
                3,
                "turn_start",
                None,
                AgentAction("sensitive-agent-prompt"),
            ),
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="sensitive-response")

    actions = HookActionExecutor(
        tmp_path,
        http_client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    hooks = HookRuntime(snapshot, HookEventFactory(tmp_path), actions, diagnostics.append)
    hooks.begin_session("s1", "new")
    provider = ScriptedProvider(
        [[StreamEvent(type="text_delta", text="still done"), StreamEvent(type="message_done")]]
    )
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,
    )

    events = list(agent.run(AgentRequest("continue")))
    hooks.close()

    assert events[-1].stop_reason == "completed"
    assert [item.code for item in diagnostics] == [
        "command_failed",
        "http_status",
        "agent_not_implemented",
    ]
    rendered = " ".join(item.message for item in diagnostics)
    assert "sensitive-response" not in rendered
    assert "sensitive-agent-prompt" not in rendered


def test_once_resets_at_new_session_boundary(tmp_path: Path) -> None:
    snapshot = HookSnapshot(
        (
            HookRule(
                "project:1",
                "project",
                tmp_path / ".mycode/hooks.yaml",
                1,
                "turn_start",
                None,
                CommandAction("printf x >> once.txt", once=True),
            ),
        )
    )
    actions = HookActionExecutor(tmp_path)
    hooks = HookRuntime(snapshot, HookEventFactory(tmp_path), actions)

    hooks.begin_session("s1", "new")
    hooks.begin_turn("default", "message")
    hooks.end_turn("completed")
    hooks.begin_turn("default", "message")
    hooks.end_turn("completed")
    hooks.end_session("switched")
    hooks.begin_session("s2", "new")
    hooks.begin_turn("default", "message")
    hooks.end_turn("completed")
    hooks.close()

    assert (tmp_path / "once.txt").read_text(encoding="utf-8") == "xx"
