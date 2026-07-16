import time
from collections.abc import Mapping
from pathlib import Path

from mycode.permissions.models import PermissionDecision
from mycode.tools.registry import ToolRegistry, create_default_registry
from mycode.types import ToolCall, ToolContext, ToolResult, ToolSpec
from mycode.tools.executor import ToolExecutor


def context(tmp_path: Path, timeout: float = 1.0) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, timeout_seconds=timeout)


class AllowPermissions:
    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        return PermissionDecision(True, "test_allow", "allowed", call.name)


class DenyPermissions:
    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        target = call.arguments.get("command", call.name)
        return PermissionDecision(False, "rule_deny", "denied", str(target))


def test_executor_runs_registered_tool(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(create_default_registry(), context(tmp_path), AllowPermissions())

    result = executor.execute(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}))

    assert result.ok is True


def test_default_executor_runs_read_tool_without_approval(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    result = ToolExecutor(create_default_registry(), context(tmp_path)).execute(
        ToolCall(id="1", name="read_file", arguments={"path": "a.txt"})
    )

    assert result.ok is True
    assert result.data["content"] == "hello"


def test_executor_wraps_unknown_tool(tmp_path: Path) -> None:
    result = ToolExecutor(create_default_registry(), context(tmp_path), AllowPermissions()).execute(
        ToolCall(id="1", name="missing", arguments={})
    )

    assert result.ok is False
    assert "未知工具" in result.message


class BrokenTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="broken", description="broken", parameters={"type": "object"})

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        raise RuntimeError("boom")


class SlowTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="slow", description="slow", parameters={"type": "object"})

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        time.sleep(0.2)
        return ToolResult(ok=True, message="late", data={})


def test_executor_wraps_tool_exception(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(BrokenTool())

    result = ToolExecutor(registry, context(tmp_path), AllowPermissions()).execute(ToolCall(id="1", name="broken", arguments={}))

    assert result.ok is False
    assert "boom" in result.message


def test_executor_timeout(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(SlowTool())

    result = ToolExecutor(registry, context(tmp_path, timeout=0.01), AllowPermissions()).execute(
        ToolCall(id="1", name="slow", arguments={})
    )

    assert result.ok is False
    assert "超时" in result.message


def test_permission_denial_does_not_call_tool(tmp_path: Path) -> None:
    record: list[str] = []

    class RecordingTool:
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(name="record", description="record", parameters={"type": "object"})

        def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
            record.append("called")
            return ToolResult(ok=True, message="called", data={})

    registry = ToolRegistry()
    registry.register(RecordingTool())
    result = ToolExecutor(registry, context(tmp_path), DenyPermissions()).execute(
        ToolCall(id="1", name="record", arguments={})
    )

    assert not result.ok
    assert result.data["permission_reason"] == "rule_deny"
    assert record == []


def test_permission_denial_redacts_sensitive_target(tmp_path: Path) -> None:
    result = ToolExecutor(create_default_registry(), context(tmp_path), DenyPermissions()).execute(
        ToolCall(id="1", name="run_command", arguments={"command": "API_KEY=secret-value echo ok"})
    )

    assert "secret-value" not in result.data["permission_target"]
    assert "<redacted>" in result.data["permission_target"]
