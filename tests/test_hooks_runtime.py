from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mycode.context.models import CompactionReport
from mycode.hooks.events import HookEventFactory
from mycode.hooks.models import (
    AgentAction,
    CommandAction,
    HookActionOutcome,
    HookCondition,
    HookRule,
    HookSnapshot,
    PromptAction,
)
from mycode.hooks.conditions import parse_clause
from mycode.hooks.runtime import HookRuntime
from mycode.types import ToolCall, ToolExecutionResult, ToolResult


class FakeActions:
    def __init__(self) -> None:
        self.calls = []
        self.outcomes: dict[str, list[HookActionOutcome]] = defaultdict(list)
        self.closed = False

    def execute(self, action, event, callback=None):
        self.calls.append((action, event, callback))
        if isinstance(action, AgentAction):
            return HookActionOutcome("placeholder", "not implemented", "agent_not_implemented")
        values = self.outcomes[getattr(action, "command", "")]
        return values.pop(0) if values else HookActionOutcome("success", code="ok")

    def close(self) -> None:
        self.closed = True


def rule(
    index: int,
    event: str,
    action=None,
    condition: HookCondition | None = None,
) -> HookRule:
    return HookRule(  # type: ignore[arg-type]
        rule_id=f"project:{index}",
        source="project",
        source_path=Path("/workspace/.mycode/hooks.yaml"),
        source_index=index,
        event=event,
        condition=condition,
        action=action or CommandAction(str(index)),
    )


def runtime(tmp_path: Path, rules: list[HookRule], actions=None, diagnostics=None) -> HookRuntime:
    events = HookEventFactory(
        tmp_path,
        clock=lambda: datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    return HookRuntime(
        HookSnapshot(tuple(rules)),
        events,
        actions,
        diagnostics.append if diagnostics is not None else None,
    )


def test_dispatches_rules_in_snapshot_order_with_same_immutable_payload(tmp_path: Path) -> None:
    actions = FakeActions()
    matching = HookCondition("all", (parse_clause("turn.mode(default)", "turn_start"),))
    hooks = runtime(
        tmp_path,
        [rule(1, "turn_start"), rule(2, "turn_start", condition=matching), rule(3, "turn_end")],
        actions,
    )
    hooks.begin_session("s1", "new")
    hooks.begin_turn("default", "message")

    assert [call[0].command for call in actions.calls] == ["1", "2"]
    assert actions.calls[0][1] is actions.calls[1][1]
    assert actions.calls[0][1].payload["turn"]["id"] == 1


def test_all_ten_events_dispatch_and_unsuccessful_compaction_is_skipped(tmp_path: Path) -> None:
    event_names = [
        "session_start",
        "session_end",
        "turn_start",
        "turn_end",
        "message_received",
        "message_sent",
        "tool_before",
        "tool_after",
        "context_compacted",
        "agent_error",
    ]
    actions = FakeActions()
    hooks = runtime(tmp_path, [rule(i, name) for i, name in enumerate(event_names, 1)], actions)
    call = ToolCall("c1", "read_file", {"path": "README.md"})
    result = ToolExecutionResult.same(ToolResult(True, "ok", {}))

    hooks.begin_session("s1", "restored")
    hooks.begin_turn("plan", "skill")
    hooks.message_received("review")
    hooks.before_tool(call)
    hooks.after_tool(call, result, "tool")
    hooks.context_compacted(CompactionReport("not_needed", "automatic", 10, 10, 100))
    hooks.context_compacted(CompactionReport("success", "automatic", 100, 20, 80))
    hooks.agent_error("stream_error", "safe")
    hooks.message_sent("done")
    hooks.end_turn("completed")
    hooks.end_session("exit")

    assert [item[1].name for item in actions.calls] == [
        "session_start",
        "turn_start",
        "message_received",
        "tool_before",
        "tool_after",
        "context_compacted",
        "agent_error",
        "message_sent",
        "turn_end",
        "session_end",
    ]


@pytest.mark.parametrize(
    ("outcomes", "expected_calls"),
    [
        ([HookActionOutcome("success")], 1),
        ([HookActionOutcome("submitted")], 1),
        ([HookActionOutcome("denied", "blocked")], 1),
        ([HookActionOutcome("failed"), HookActionOutcome("success")], 2),
        ([HookActionOutcome("cancelled"), HookActionOutcome("success")], 2),
    ],
)
def test_once_consumption_matrix(
    tmp_path: Path,
    outcomes: list[HookActionOutcome],
    expected_calls: int,
) -> None:
    actions = FakeActions()
    actions.outcomes["once"] = list(outcomes)
    hooks = runtime(
        tmp_path,
        [rule(1, "tool_before", CommandAction("once", once=True))],
        actions,
    )
    hooks.begin_session("s1", "new")
    call = ToolCall("c1", "read_file", {"path": "README.md"})

    hooks.before_tool(call)
    hooks.before_tool(call)

    assert len(actions.calls) == expected_calls


def test_once_prompt_and_placeholder_consume_and_new_session_resets(tmp_path: Path) -> None:
    actions = FakeActions()
    hooks = runtime(
        tmp_path,
        [
            rule(1, "turn_start", PromptAction("one", once=True)),
            rule(2, "turn_start", AgentAction("later", once=True)),
        ],
        actions,
    )
    hooks.begin_session("s1", "new")
    hooks.begin_turn("default", "message")
    hooks.end_turn("completed")
    hooks.begin_turn("default", "message")
    assert [item.content for item in hooks.reserve_prompts().instructions] == ["one"]
    assert len(actions.calls) == 1

    hooks.begin_session("s2", "new")
    hooks.begin_turn("default", "message")
    assert [item.content for item in hooks.reserve_prompts().instructions] == ["one"]
    assert len(actions.calls) == 2


def test_tool_deny_stops_remaining_rules_and_returns_reason(tmp_path: Path) -> None:
    actions = FakeActions()
    actions.outcomes["deny"] = [HookActionOutcome("denied", "unsafe", "command_denied")]
    hooks = runtime(
        tmp_path,
        [rule(1, "tool_before", CommandAction("deny")), rule(2, "tool_before")],
        actions,
    )
    hooks.begin_session("s1", "new")

    result = hooks.before_tool(ToolCall("c1", "run_command", {"command": "danger"}))

    assert result.denied and result.reason == "unsafe"
    assert [item[0].command for item in actions.calls] == ["deny"]


def test_failed_placeholder_and_async_callback_emit_bounded_safe_diagnostics(tmp_path: Path) -> None:
    diagnostics = []
    actions = FakeActions()
    actions.outcomes["fail"] = [HookActionOutcome("failed", "x" * 3000, "command_error")]
    hooks = runtime(
        tmp_path,
        [rule(1, "turn_start", CommandAction("fail")), rule(2, "turn_start", AgentAction("secret"))],
        actions,
        diagnostics,
    )
    hooks.begin_session("s1", "new")
    hooks.begin_turn("default", "message")
    actions.calls[0][2](HookActionOutcome("failed", "async-safe", "http_error"))

    assert [item.code for item in diagnostics] == [
        "command_error",
        "agent_not_implemented",
        "http_error",
    ]
    assert len(diagnostics[0].message) == 2_000
    assert all("secret" not in item.message for item in diagnostics)


def test_prompt_lease_reserve_refresh_commit_and_release(tmp_path: Path) -> None:
    hooks = runtime(
        tmp_path,
        [rule(1, "turn_start", PromptAction("first")), rule(2, "context_compacted", PromptAction("second"))],
    )
    hooks.begin_session("s1", "new")
    hooks.begin_turn("default", "message")

    lease = hooks.reserve_prompts()
    same = hooks.reserve_prompts()
    assert same == lease
    assert [item.content for item in lease.instructions] == ["first"]

    hooks.context_compacted(CompactionReport("success", "automatic", 100, 30, 80))
    refreshed = hooks.refresh_prompt_lease(lease.lease_id)
    assert [item.content for item in refreshed.instructions] == ["first", "second"]
    hooks.release_prompt_lease(lease.lease_id)
    retry = hooks.reserve_prompts()
    assert [item.content for item in retry.instructions] == ["first", "second"]
    hooks.commit_prompt_lease(retry.lease_id)
    assert hooks.reserve_prompts().instructions == ()

    with pytest.raises(ValueError):
        hooks.commit_prompt_lease("expired")


def test_close_is_idempotent_and_closes_action_executor(tmp_path: Path) -> None:
    actions = FakeActions()
    hooks = runtime(tmp_path, [], actions)
    hooks.close()
    hooks.close()
    assert actions.closed
