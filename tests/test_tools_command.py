from pathlib import Path

from mycode.tools.command import RunCommandTool
from mycode.types import ToolContext


def context(tmp_path: Path, max_output_chars: int = 1000) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, timeout_seconds=1.0, max_output_chars=max_output_chars)


def test_run_command_success_and_cwd(tmp_path: Path) -> None:
    result = RunCommandTool().run({"command": "pwd"}, context(tmp_path))

    assert result.ok is True
    assert result.data["exit_code"] == 0
    assert str(tmp_path) in str(result.data["stdout"])


def test_run_command_failure_returns_structured_result(tmp_path: Path) -> None:
    result = RunCommandTool().run({"command": "exit 7"}, context(tmp_path))

    assert result.ok is False
    assert result.data["exit_code"] == 7


def test_run_command_timeout(tmp_path: Path) -> None:
    result = RunCommandTool().run(
        {"command": "sleep 2", "timeout_seconds": 0.1},
        context(tmp_path),
    )

    assert result.ok is False
    assert "超时" in result.message


def test_run_command_truncates_output(tmp_path: Path) -> None:
    result = RunCommandTool().run(
        {"command": "printf abcdef"},
        context(tmp_path, max_output_chars=3),
    )

    assert result.data["stdout"] == "abc"
    assert result.data["stdout_truncated"] is True
