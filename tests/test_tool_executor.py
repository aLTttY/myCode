import time
from collections.abc import Mapping
from pathlib import Path

from mycode.tools.registry import ToolRegistry, create_default_registry
from mycode.types import ToolCall, ToolContext, ToolResult, ToolSpec
from mycode.tools.executor import ToolExecutor


def context(tmp_path: Path, timeout: float = 1.0) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, timeout_seconds=timeout)


def test_executor_runs_registered_tool(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    executor = ToolExecutor(create_default_registry(), context(tmp_path))

    result = executor.execute(ToolCall(id="1", name="read_file", arguments={"path": "a.txt"}))

    assert result.ok is True


def test_executor_wraps_unknown_tool(tmp_path: Path) -> None:
    result = ToolExecutor(create_default_registry(), context(tmp_path)).execute(
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

    result = ToolExecutor(registry, context(tmp_path)).execute(ToolCall(id="1", name="broken", arguments={}))

    assert result.ok is False
    assert "boom" in result.message


def test_executor_timeout(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(SlowTool())

    result = ToolExecutor(registry, context(tmp_path, timeout=0.01)).execute(
        ToolCall(id="1", name="slow", arguments={})
    )

    assert result.ok is False
    assert "超时" in result.message
