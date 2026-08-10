from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import mycode.tools.git as git_module
from mycode.tools.git import ReadGitChangesTool
from mycode.types import ToolContext, ToolExecutionResult, ToolResult


def display_result(result: ToolResult | ToolExecutionResult) -> ToolResult:
    return result.display if isinstance(result, ToolExecutionResult) else result


def complete_result(result: ToolResult | ToolExecutionResult) -> ToolResult:
    return result.complete if isinstance(result, ToolExecutionResult) else result


def run_git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )


def initialized_repo(root: Path) -> None:
    run_git(root, "init", "-q")
    run_git(root, "config", "user.email", "test@example.com")
    run_git(root, "config", "user.name", "Test")
    (root / "tracked.txt").write_text("before\n", encoding="utf-8")
    run_git(root, "add", "tracked.txt")
    run_git(root, "commit", "-qm", "initial")


def test_git_tool_schema_and_runtime_reject_arguments(tmp_path: Path) -> None:
    tool = ReadGitChangesTool()

    assert tool.spec.parameters == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    result = display_result(tool.run({"revision": "HEAD"}, ToolContext(tmp_path)))

    assert not result.ok
    assert result.data["reason_code"] == "invalid_arguments"


def test_git_tool_reads_staged_unstaged_and_untracked_changes(tmp_path: Path) -> None:
    initialized_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")
    (tmp_path / "staged.txt").write_text("staged body\n", encoding="utf-8")
    run_git(tmp_path, "add", "staged.txt")
    (tmp_path / "untracked.txt").write_text("untracked secret body\n", encoding="utf-8")

    result = display_result(ReadGitChangesTool().run({}, ToolContext(tmp_path)))

    assert result.ok
    assert "tracked.txt" in result.data["status"]
    assert "staged.txt" in result.data["status"]
    assert "untracked.txt" in result.data["status"]
    assert "after" in result.data["unstaged_diff"]
    assert "staged body" in result.data["staged_diff"]
    assert "untracked secret body" not in str(result.data)


def test_git_tool_uses_fixed_non_shell_commands_and_shared_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    clock = iter((100.0, 100.1, 100.4, 100.9))
    monkeypatch.setattr(git_module.time, "monotonic", lambda: next(clock))

    def fake_run(command, **kwargs):
        calls.append((tuple(command), kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(git_module.subprocess, "run", fake_run)

    result = display_result(
        ReadGitChangesTool().run({}, ToolContext(tmp_path, timeout_seconds=2.0))
    )

    assert result.ok
    assert [command for command, _ in calls] == [
        ("git", "status", "--short", "--untracked-files=all"),
        ("git", "diff", "--no-ext-diff", "--no-textconv", "--"),
        ("git", "diff", "--cached", "--no-ext-diff", "--no-textconv", "--"),
    ]
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert all(kwargs["cwd"] == tmp_path for _, kwargs in calls)
    timeouts = [float(kwargs["timeout"]) for _, kwargs in calls]
    assert timeouts == pytest.approx([1.9, 1.6, 1.1])
    assert all(kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0" for _, kwargs in calls)


def test_git_tool_truncates_display_across_all_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outputs = iter(("s" * 8, "u" * 8, "c" * 8))

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(git_module.subprocess, "run", fake_run)

    result = ReadGitChangesTool().run({}, ToolContext(tmp_path, max_output_chars=10))

    assert isinstance(result, ToolExecutionResult)
    assert result.display.data["truncated"] is True
    shown = sum(
        len(str(result.display.data[key]))
        for key in ("status", "unstaged_diff", "staged_diff")
    )
    assert shown == 10
    assert result.complete.data["unstaged_diff"] == "u" * 8
    assert result.complete.data["truncated"] is False


def test_git_tool_returns_safe_errors_for_non_repo_and_missing_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_repo = display_result(ReadGitChangesTool().run({}, ToolContext(tmp_path)))
    assert not non_repo.ok
    assert non_repo.data["reason_code"] == "git_failed"
    assert "fatal" not in str(non_repo.data).lower()

    def missing(*args, **kwargs):
        raise OSError("secret executable path")

    monkeypatch.setattr(git_module.subprocess, "run", missing)
    unavailable = display_result(ReadGitChangesTool().run({}, ToolContext(tmp_path)))
    assert not unavailable.ok
    assert unavailable.data["reason_code"] == "git_unavailable"
    assert "secret" not in unavailable.message
    assert "secret" not in str(unavailable.data)


def test_git_tool_timeout_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="secret")

    monkeypatch.setattr(git_module.subprocess, "run", timeout)

    result = display_result(
        ReadGitChangesTool().run({}, ToolContext(tmp_path, timeout_seconds=0.5))
    )

    assert not result.ok
    assert result.data["reason_code"] == "timeout"
    assert result.data["stage"] == "status"
    assert "secret" not in str(result.data)
