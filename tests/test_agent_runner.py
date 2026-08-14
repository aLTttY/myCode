from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from pathlib import Path

from mycode.agent.cancellation import CancellationToken
from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.context.models import CompactionReport, PreparedContext
from mycode.hooks.events import HookEventFactory
from mycode.hooks.models import HookPromptLease, HookRule, HookSnapshot, PromptAction
from mycode.hooks.runtime import HookRuntime
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.skills.models import (
    IsolatedSkillResult,
    SkillDefinition,
    SkillInvocation,
    SkillSnapshot,
    immutable_mapping,
)
from mycode.skills.runtime import SkillRuntime
from mycode.tools.registry import create_default_registry
from mycode.types import ContextConfig, Message, ProviderError, StreamEvent, TokenUsage, ToolContext


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


def skill_definition(name: str, *, mode: str = "shared", sop: str = "Follow the secret SOP.") -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description=f"{name} description",
        allowed_tools=("read_file",),
        mode=mode,  # type: ignore[arg-type]
        history=0 if mode == "isolated" else None,
        model=None,
        sop=sop,
        compiled_sop=sop,
        source="project",
        source_id=f"test:{name}",
        package_root=None,
        dedicated_tools=(),
        fingerprint=f"fp:{name}",
    )


def skill_runtime(*definitions: SkillDefinition) -> SkillRuntime:
    return SkillRuntime(
        SkillSnapshot(
            definitions=immutable_mapping({definition.name: definition for definition in definitions}),
            dedicated_tools=immutable_mapping(),
        )
    )


class RecordingIsolatedExecutor:
    def __init__(self, result: IsolatedSkillResult | None = None) -> None:
        self.result = result or IsolatedSkillResult("completed", "isolated summary")
        self.calls: list[tuple[SkillInvocation, SkillDefinition, Sequence[Message]]] = []

    def run(
        self,
        invocation,
        definition,
        history,
        cancellation,
        *,
        dynamic_instructions=(),
        on_instructions_commit=None,
        on_instructions_release=None,
    ):
        self.calls.append((invocation, definition, history))
        if on_instructions_commit is not None:
            on_instructions_commit()
        return self.result


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
    provider = ScriptedProvider([
        tool_call_events("1", "run_command", '{"command": "echo hello"}'),
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

    assert {tool.name for tool in provider.calls[0].tools} == {
        "read_file",
        "find_files",
        "search_code",
        "read_git_changes",
    }
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


def test_agent_runner_records_successful_input_usage_anchor(tmp_path: Path) -> None:
    provider = ScriptedProvider([
        [
            StreamEvent(type="token_usage", token_usage=TokenUsage(input_tokens=321, output_tokens=1)),
            StreamEvent(type="text_delta", text="done"),
            StreamEvent(type="message_done"),
        ]
    ])
    agent = runner(provider, tmp_path)

    list(agent.run(AgentRequest("hello")))

    assert agent.context_manager.state.token_anchor is not None
    assert agent.context_manager.state.token_anchor.input_tokens == 321


def test_agent_runner_refuses_over_budget_request_before_provider_call(tmp_path: Path) -> None:
    provider = ScriptedProvider([[StreamEvent(type="text_delta", text="must not run")]])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        context_config=ContextConfig(window_tokens=1),
    )

    events = list(agent.run(AgentRequest("too large")))

    assert provider.calls == []
    assert any(event.type == "error" and event.stop_reason == "context_overflow" for event in events)
    assert events[-1].stop_reason == "context_overflow"
    assert "/compact" in events[-1].message


def test_agent_runner_manual_compact_does_not_add_user_message(tmp_path: Path) -> None:
    provider = ScriptedProvider([[StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")]])
    agent = runner(provider, tmp_path)
    list(agent.run(AgentRequest("hello")))
    before = agent.messages

    report = agent.compact()

    assert report.status == "not_needed"
    assert agent.messages == before


def test_agent_runner_context_status_is_local_and_mode_aware(tmp_path: Path) -> None:
    provider = ScriptedProvider([])
    agent = runner(provider, tmp_path)

    default_status = agent.context_status("default")
    plan_status = agent.context_status("plan")

    assert provider.calls == []
    assert default_status.message_count == 0
    assert plan_status.message_count == 0
    assert default_status.window_tokens == plan_status.window_tokens
    assert default_status.estimated_tokens >= plan_status.estimated_tokens


def test_agent_runner_compact_can_override_last_request_mode(tmp_path: Path) -> None:
    provider = ScriptedProvider([])
    agent = runner(provider, tmp_path)
    agent._last_request = AgentRequest("last", mode="default")
    captured_tools: list[set[str]] = []

    def fake_compact(request: ChatRequest) -> CompactionReport:
        captured_tools.append({tool.name for tool in request.tools})
        return CompactionReport("not_needed", "manual", 1, 1, 1)

    agent.context_manager.compact = fake_compact  # type: ignore[method-assign]

    agent.compact("plan")

    assert captured_tools == [
        {"read_file", "find_files", "search_code", "read_git_changes"}
    ]
    assert provider.calls == []


def test_load_skill_activates_shared_sop_and_reprojects_tools(tmp_path: Path) -> None:
    definition = skill_definition("demo", sop="SECRET SHARED SOP")
    runtime = skill_runtime(definition)
    provider = ScriptedProvider([
        tool_call_events("load-1", "load_skill", '{"name":"demo"}'),
        [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")],
    ])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        skill_runtime=runtime,
    )

    events = list(agent.run(AgentRequest("use the reusable workflow")))

    assert events[-1].stop_reason == "completed"
    assert "load_skill" in {tool.name for tool in provider.calls[0].tools}
    assert "write_file" in {tool.name for tool in provider.calls[0].tools}
    assert {tool.name for tool in provider.calls[1].tools} == {"read_file", "load_skill"}
    assert "demo description" in provider.calls[0].optional_system_prompt
    assert "SECRET SHARED SOP" not in provider.calls[0].optional_system_prompt
    assert "SECRET SHARED SOP" in provider.calls[1].optional_system_prompt
    assert runtime.active_names() == ("demo",)


def test_load_skill_runs_isolated_mode_without_activating_it(tmp_path: Path) -> None:
    definition = skill_definition("audit", mode="isolated")
    runtime = skill_runtime(definition)
    isolated = RecordingIsolatedExecutor()
    provider = ScriptedProvider([
        tool_call_events("load-1", "load_skill", '{"name":"audit"}'),
        [StreamEvent(type="text_delta", text="main answer"), StreamEvent(type="message_done")],
    ])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        skill_runtime=runtime,
        isolated_skill_executor=isolated,
    )

    events = list(agent.run(AgentRequest("inspect this input")))

    assert events[-1].stop_reason == "completed"
    assert runtime.active_names() == ()
    assert isolated.calls[0][0].input_text == "inspect this input"
    assert isolated.calls[0][0].origin == "agent"
    tool_message = next(message for message in provider.calls[1].messages if message.role == "tool")
    assert "isolated summary" in tool_message.content


def test_direct_isolated_skill_returns_summary_and_records_one_turn(tmp_path: Path) -> None:
    definition = skill_definition("audit", mode="isolated")
    isolated = RecordingIsolatedExecutor()
    agent = AgentRunner(
        ScriptedProvider([]),
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        skill_runtime=skill_runtime(definition),
        isolated_skill_executor=isolated,
    )

    events = list(agent.invoke_skill("audit", "target input"))

    assert [event.text for event in events if event.type == "text_delta"] == ["isolated summary"]
    assert events[-1].stop_reason == "completed"
    assert [message.role for message in agent.messages] == ["user", "assistant"]
    assert "target input" in agent.messages[0].content
    assert agent.messages[1].content == "isolated summary"


def test_new_session_clears_shared_skill_activation(tmp_path: Path) -> None:
    definition = skill_definition("demo")
    runtime = skill_runtime(definition)
    runtime.activate_shared("demo")
    agent = AgentRunner(
        ScriptedProvider([]),
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        skill_runtime=runtime,
    )

    agent.new_session()

    assert runtime.active_names() == ()


class RecordingHookLifecycle:
    def __init__(self) -> None:
        self.events = []
        self._lease = 0

    def begin_turn(self, mode, input_kind):
        self.events.append(("turn_start", mode, input_kind))

    def message_received(self, content):
        self.events.append(("message_received", content))

    def message_sent(self, content):
        self.events.append(("message_sent", content))

    def end_turn(self, reason):
        self.events.append(("turn_end", reason))

    def agent_error(self, code, message):
        self.events.append(("agent_error", code, message))

    def before_tool(self, call):
        from mycode.hooks.models import HookDispatchResult

        self.events.append(("tool_before", call.id))
        return HookDispatchResult()

    def after_tool(self, call, result, source):
        self.events.append(("tool_after", call.id, source))

    def context_compacted(self, report):
        self.events.append(("context_compacted", report.status))

    def reserve_prompts(self):
        self._lease += 1
        return HookPromptLease(f"lease-{self._lease}", ())

    def refresh_prompt_lease(self, lease_id):
        return HookPromptLease(lease_id, ())

    def commit_prompt_lease(self, lease_id):
        return None

    def release_prompt_lease(self, lease_id):
        return None


def test_main_lifecycle_wraps_multiple_model_tool_iterations_once(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    hooks = RecordingHookLifecycle()
    provider = ScriptedProvider(
        [
            tool_call_events("1", "read_file", '{"path":"a.txt"}'),
            [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")],
        ]
    )
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,  # type: ignore[arg-type]
    )

    list(agent.run(AgentRequest("read it")))

    assert hooks.events == [
        ("turn_start", "default", "message"),
        ("message_received", "read it"),
        ("tool_before", "1"),
        ("tool_after", "1", "tool"),
        ("message_sent", "done"),
        ("turn_end", "completed"),
    ]


def test_structured_agent_error_is_emitted_once_before_turn_end(tmp_path: Path) -> None:
    hooks = RecordingHookLifecycle()
    agent = AgentRunner(
        BrokenProvider(),
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,  # type: ignore[arg-type]
    )

    list(agent.run(AgentRequest("broken")))

    assert [item[0] for item in hooks.events] == [
        "turn_start",
        "message_received",
        "agent_error",
        "turn_end",
    ]
    assert hooks.events[-2][1] == "stream_error"
    assert hooks.events[-1] == ("turn_end", "stream_error")


def prompt_rule(index: int, event: str, content: str) -> HookRule:
    return HookRule(  # type: ignore[arg-type]
        rule_id=f"project:{index}",
        source="project",
        source_path=Path("/workspace/.mycode/hooks.yaml"),
        source_index=index,
        event=event,
        condition=None,
        action=PromptAction(content),
    )


def test_hook_prompts_are_consumed_by_next_provider_request_only(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    hooks = HookRuntime(
        HookSnapshot(
            (
                prompt_rule(1, "turn_start", "first request only"),
                prompt_rule(2, "tool_after", "second request only"),
            )
        ),
        HookEventFactory(tmp_path),
    )
    hooks.begin_session("s1", "new")
    provider = ScriptedProvider(
        [
            tool_call_events("1", "read_file", '{"path":"a.txt"}'),
            [StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")],
        ]
    )
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,
    )

    list(agent.run(AgentRequest("read it")))

    first_dynamic = "\n".join(item.content for item in provider.calls[0].dynamic_system_messages)
    second_dynamic = "\n".join(item.content for item in provider.calls[1].dynamic_system_messages)
    assert "first request only" in first_dynamic and "first request only" not in second_dynamic
    assert "second request only" not in first_dynamic and "second request only" in second_dynamic
    assert all("request only" not in message.content for message in agent.messages)


def test_auto_compaction_prompt_refreshes_current_request_without_recompacting(tmp_path: Path) -> None:
    hooks = HookRuntime(
        HookSnapshot(
            (
                prompt_rule(1, "turn_start", "before compact"),
                prompt_rule(2, "context_compacted", "after compact"),
            )
        ),
        HookEventFactory(tmp_path),
    )
    hooks.begin_session("s1", "new")
    provider = ScriptedProvider(
        [[StreamEvent(type="text_delta", text="done"), StreamEvent(type="message_done")]]
    )
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        hook_runtime=hooks,
    )
    prepare_calls = 0

    def prepared(template):
        nonlocal prepare_calls
        prepare_calls += 1
        return PreparedContext(
            True,
            replace(template, messages=agent.messages),
            CompactionReport("success", "automatic", 100, 50, 100_000),
        )

    agent.context_manager.prepare_request = prepared  # type: ignore[method-assign]

    list(agent.run(AgentRequest("hello")))

    dynamic = "\n".join(item.content for item in provider.calls[0].dynamic_system_messages)
    assert prepare_calls == 1
    assert "before compact" in dynamic
    assert "after compact" in dynamic


def test_context_overflow_releases_prompt_lease_when_provider_not_called(tmp_path: Path) -> None:
    hooks = HookRuntime(
        HookSnapshot((prompt_rule(1, "turn_start", "keep me"),)),
        HookEventFactory(tmp_path),
    )
    hooks.begin_session("s1", "new")
    provider = ScriptedProvider([[StreamEvent(type="message_done")]])
    agent = AgentRunner(
        provider,
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        context_config=ContextConfig(window_tokens=1),
        hook_runtime=hooks,
    )

    list(agent.run(AgentRequest("too large")))

    lease = hooks.reserve_prompts()
    assert provider.calls == []
    assert [item.content for item in lease.instructions] == ["keep me"]
    hooks.release_prompt_lease(lease.lease_id)


def test_team_registry_provider_is_request_scoped_and_session_reset_revokes_binding(tmp_path: Path) -> None:
    from mycode.sessions import SessionJournal

    journal = SessionJournal(tmp_path)
    calls = []
    cleared = []
    agent = AgentRunner(
        ScriptedProvider([[StreamEvent(type="message_done")]]),
        create_default_registry(),
        ToolContext(workspace_root=tmp_path),
        session_journal=journal,
        team_registry_provider=lambda base, session_id, mode: (
            calls.append((session_id, mode)) or base.exclude(("write_file",))
        ),
        on_session_reset=cleared.append,
    )
    registry = agent._registry_for_request(AgentRequest("", mode="default"))
    assert "write_file" not in registry.names()
    old_session = journal.session_id
    agent.new_session()
    assert calls == [(old_session, "default")]
    assert cleared == [old_session]
    agent.close()
