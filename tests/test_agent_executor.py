from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import Event

from mycode.agent.cancellation import CancellationToken
from mycode.agent.events import AgentEvent
from mycode.agent.executor import BatchToolExecutor
from mycode.agent.tools import ToolBatch, ToolBatcher
from mycode.permissions.models import PermissionConfigSet, PermissionDecision, PermissionLayer
from mycode.permissions.service import PermissionService
from mycode.tools.registry import ToolRegistry, create_default_registry
from mycode.hooks.models import HookDispatchResult
from mycode.types import ToolCall, ToolContext, ToolResult, ToolSpec


def context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, timeout_seconds=1.0)


class AllowPermissions:
    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True, "test_allow", "allowed", call.name)


class DenyPermissions:
    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        return PermissionDecision(False, "test_deny", "denied", call.name)


class RecordingApproval:
    def __init__(self) -> None:
        self.calls = []

    def request(self, approval):
        self.calls.append(approval)
        return "deny"


class RecordingHooks:
    def __init__(self, denied_ids: set[str] | None = None) -> None:
        self.denied_ids = denied_ids or set()
        self.before: list[str] = []
        self.after: list[tuple[str, str]] = []

    def before_tool(self, call: ToolCall) -> HookDispatchResult:
        self.before.append(call.id)
        if call.id in self.denied_ids:
            return HookDispatchResult(True, f"blocked-{call.id}")
        return HookDispatchResult()

    def after_tool(self, call, result, source) -> None:
        self.after.append((call.id, source))


def test_cancellation_token_is_idempotent() -> None:
    token = CancellationToken()

    assert token.is_cancelled() is False
    token.cancel()
    token.cancel()
    assert token.is_cancelled() is True


def test_executor_runs_read_batch_and_returns_results(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    batch = ToolBatch(
        safety="read",
        calls=(
            ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}),
            ToolCall(id="2", name="read_file", arguments={"path": "b.txt"}),
        ),
    )

    events = list(BatchToolExecutor(create_default_registry(), context(tmp_path), AllowPermissions()).execute_batches([batch], CancellationToken()))

    assert sum(1 for event in events if getattr(event, "type", "") == "tool_call_started") == 2
    assert sum(1 for event in events if getattr(event, "type", "") == "tool_result") == 2
    assert sorted(item[0] for item in events if isinstance(item, tuple)) == ["1", "2"]
    assert all(item[1].display is item[1].complete for item in events if isinstance(item, tuple))


def test_read_batch_does_not_request_approval(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    approval = RecordingApproval()
    permissions = PermissionService(
        PermissionConfigSet(
            user=PermissionLayer("user"),
            project=PermissionLayer("project"),
            local=PermissionLayer("local"),
            effective_mode="default",
        ),
        approval,
    )
    batch = ToolBatch(
        safety="read",
        calls=(
            ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}),
            ToolCall(id="2", name="read_file", arguments={"path": "b.txt"}),
        ),
    )

    events = list(
        BatchToolExecutor(create_default_registry(), context(tmp_path), permissions).execute_batches(
            [batch], CancellationToken()
        )
    )

    assert approval.calls == []
    assert all(item[1].ok for item in events if isinstance(item, tuple))


class RecordingTool:
    def __init__(self, name: str, record: list[str]) -> None:
        self._spec = ToolSpec(name=name, description=name, parameters={"type": "object"})
        self.record = record

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        self.record.append(self.spec.name)
        return ToolResult(ok=True, message=self.spec.name, data={})


class CoordinatedReadTool(RecordingTool):
    def __init__(self, name: str, record: list[str], release_first: Event) -> None:
        super().__init__(name, record)
        self.release_first = release_first

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        if self.spec.name == "read_file":
            assert self.release_first.wait(timeout=1)
            return super().run(arguments, context)
        result = super().run(arguments, context)
        self.release_first.set()
        return result


def test_executor_runs_side_effect_batch_serially(tmp_path: Path) -> None:
    record: list[str] = []
    registry = ToolRegistry()
    registry.register(RecordingTool("write_file", record))
    registry.register(RecordingTool("edit_file", record))
    batch = ToolBatch(
        safety="side_effect",
        calls=(
            ToolCall(id="1", name="write_file", arguments={}),
            ToolCall(id="2", name="edit_file", arguments={}),
        ),
    )

    list(BatchToolExecutor(registry, context(tmp_path), AllowPermissions()).execute_batches([batch], CancellationToken()))

    assert record == ["write_file", "edit_file"]


def test_executor_runs_mcp_tools_as_one_serial_side_effect_batch(tmp_path: Path) -> None:
    record: list[str] = []
    registry = ToolRegistry()
    registry.register(RecordingTool("alpha__first", record))
    registry.register(RecordingTool("alpha__second", record))
    calls = (
        ToolCall(id="1", name="alpha__first", arguments={}),
        ToolCall(id="2", name="alpha__second", arguments={}),
    )
    batches = ToolBatcher().batch(calls)

    list(
        BatchToolExecutor(registry, context(tmp_path), AllowPermissions()).execute_batches(
            batches,
            CancellationToken(),
        )
    )

    assert len(batches) == 1 and batches[0].safety == "side_effect"
    assert record == ["alpha__first", "alpha__second"]


def test_executor_runs_mixed_batches_without_crossing_order(tmp_path: Path) -> None:
    record: list[str] = []
    registry = ToolRegistry()
    registry.register(RecordingTool("read_file", record))
    registry.register(RecordingTool("write_file", record))
    registry.register(RecordingTool("edit_file", record))
    batches = [
        ToolBatch(safety="read", calls=(ToolCall(id="1", name="read_file", arguments={}),)),
        ToolBatch(
            safety="side_effect",
            calls=(
                ToolCall(id="2", name="write_file", arguments={}),
                ToolCall(id="3", name="edit_file", arguments={}),
            ),
        ),
    ]

    events = list(BatchToolExecutor(registry, context(tmp_path), AllowPermissions()).execute_batches(batches, CancellationToken()))

    assert record == ["read_file", "write_file", "edit_file"]
    assert [item[0] for item in events if isinstance(item, tuple)] == ["1", "2", "3"]


def test_concurrent_read_completion_keeps_original_call_order(tmp_path: Path) -> None:
    record: list[str] = []
    release_first = Event()
    registry = ToolRegistry()
    registry.register(CoordinatedReadTool("read_file", record, release_first))
    registry.register(CoordinatedReadTool("find_files", record, release_first))
    batch = ToolBatch(
        safety="read",
        calls=(
            ToolCall(id="1", name="read_file", arguments={}),
            ToolCall(id="2", name="find_files", arguments={}),
        ),
    )

    events = list(
        BatchToolExecutor(registry, context(tmp_path), AllowPermissions()).execute_batches(
            [batch], CancellationToken()
        )
    )

    completion_ids = [
        event.tool_call_id
        for event in events
        if isinstance(event, AgentEvent) and event.type == "tool_result"
    ]
    history_ids = [item[0] for item in events if isinstance(item, tuple)]
    assert completion_ids == ["2", "1"]
    assert history_ids == ["1", "2"]


def test_executor_returns_structured_unknown_tool_result(tmp_path: Path) -> None:
    batch = ToolBatch(safety="side_effect", calls=(ToolCall(id="1", name="missing", arguments={}),))

    events = list(BatchToolExecutor(create_default_registry(), context(tmp_path), AllowPermissions()).execute_batches([batch], CancellationToken()))
    result = next(item[1] for item in events if isinstance(item, tuple))

    assert result.ok is False
    assert "未知工具" in result.message
    assert result.data == {"tool": "missing"}


def test_executor_stops_when_cancelled(tmp_path: Path) -> None:
    token = CancellationToken()
    token.cancel()
    batch = ToolBatch(safety="side_effect", calls=(ToolCall(id="1", name="read_file", arguments={}),))

    events = list(BatchToolExecutor(create_default_registry(), context(tmp_path), AllowPermissions()).execute_batches([batch], token))

    assert events == []


def test_hook_denial_skips_tool_start_permission_and_execution(tmp_path: Path) -> None:
    record: list[str] = []
    registry = ToolRegistry()
    registry.register(RecordingTool("write_file", record))

    class CountingPermissions(AllowPermissions):
        calls = 0

        def authorize(self, call, tool_context):
            self.calls += 1
            return super().authorize(call, tool_context)

    permissions = CountingPermissions()
    hooks = RecordingHooks({"1"})
    batch = ToolBatch(
        safety="side_effect",
        calls=(
            ToolCall("1", "write_file", {}),
            ToolCall("2", "write_file", {}),
        ),
    )

    events = list(
        BatchToolExecutor(registry, context(tmp_path), permissions, hooks).execute_batches(
            [batch], CancellationToken()
        )
    )

    starts = [item.tool_call_id for item in events if isinstance(item, AgentEvent) and item.type == "tool_call_started"]
    results = [item for item in events if isinstance(item, tuple)]
    assert starts == ["2"]
    assert permissions.calls == 1
    assert record == ["write_file"]
    assert not results[0][1].ok and results[0][1].message == "blocked-1"
    assert hooks.before == ["1", "2"]
    assert hooks.after == [("1", "hook"), ("2", "tool")]


def test_tool_after_sources_cover_validation_and_permission(tmp_path: Path) -> None:
    hooks = RecordingHooks()
    unknown = ToolBatch(
        safety="side_effect",
        calls=(ToolCall("unknown", "missing", {}),),
    )
    list(
        BatchToolExecutor(
            create_default_registry(), context(tmp_path), AllowPermissions(), hooks
        ).execute_batches([unknown], CancellationToken())
    )

    hooks_denied = RecordingHooks()
    denied = ToolBatch(
        safety="side_effect",
        calls=(ToolCall("denied", "run_command", {"command": "echo ok"}),),
    )
    list(
        BatchToolExecutor(
            create_default_registry(), context(tmp_path), DenyPermissions(), hooks_denied
        ).execute_batches([denied], CancellationToken())
    )

    assert hooks.after == [("unknown", "validation")]
    assert hooks_denied.after == [("denied", "permission")]


def test_read_hook_after_order_is_original_even_when_completion_order_differs(tmp_path: Path) -> None:
    record: list[str] = []
    release_first = Event()
    registry = ToolRegistry()
    registry.register(CoordinatedReadTool("read_file", record, release_first))
    registry.register(CoordinatedReadTool("find_files", record, release_first))
    hooks = RecordingHooks()
    batch = ToolBatch(
        safety="read",
        calls=(
            ToolCall("1", "read_file", {}),
            ToolCall("2", "find_files", {}),
        ),
    )

    list(
        BatchToolExecutor(registry, context(tmp_path), AllowPermissions(), hooks).execute_batches(
            [batch], CancellationToken()
        )
    )

    assert hooks.before == ["1", "2"]
    assert hooks.after == [("1", "tool"), ("2", "tool")]
