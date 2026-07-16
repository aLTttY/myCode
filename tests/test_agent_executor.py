from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from mycode.agent.cancellation import CancellationToken
from mycode.agent.executor import BatchToolExecutor
from mycode.agent.tools import ToolBatch
from mycode.permissions.models import PermissionConfigSet, PermissionDecision, PermissionLayer
from mycode.permissions.service import PermissionService
from mycode.tools.registry import ToolRegistry, create_default_registry
from mycode.types import ToolCall, ToolContext, ToolResult, ToolSpec


def context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, timeout_seconds=1.0)


class AllowPermissions:
    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True, "test_allow", "allowed", call.name)


class RecordingApproval:
    def __init__(self) -> None:
        self.calls = []

    def request(self, approval):
        self.calls.append(approval)
        return "deny"


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
