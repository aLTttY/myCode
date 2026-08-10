from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping

from mycode.tools.base import execution_result, result_error, result_ok
from mycode.types import ToolContext, ToolExecutionResult, ToolResult, ToolSpec


_GIT_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("status", ("git", "status", "--short", "--untracked-files=all")),
    (
        "unstaged_diff",
        ("git", "diff", "--no-ext-diff", "--no-textconv", "--"),
    ),
    (
        "staged_diff",
        ("git", "diff", "--cached", "--no-ext-diff", "--no-textconv", "--"),
    ),
)


class ReadGitChangesTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_git_changes",
            description=(
                "Read the current workspace Git status plus staged and unstaged diffs. "
                "This tool accepts no arguments and does not read untracked file contents."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )

    def run(
        self,
        arguments: Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult | ToolExecutionResult:
        if arguments:
            return result_error(
                "read_git_changes 不接受参数。",
                reason_code="invalid_arguments",
            )

        deadline = time.monotonic() + max(0.0, context.timeout_seconds)
        outputs: dict[str, str] = {}
        environment = dict(os.environ)
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        environment["GIT_PAGER"] = "cat"

        for stage, command in _GIT_STAGES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _timeout_result(stage, context.timeout_seconds)
            try:
                completed = subprocess.run(
                    command,
                    cwd=context.workspace_root,
                    shell=False,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=remaining,
                    check=False,
                    env=environment,
                )
            except subprocess.TimeoutExpired:
                return _timeout_result(stage, context.timeout_seconds)
            except OSError as exc:
                return result_error(
                    "无法启动 Git 读取工作区变更。",
                    reason_code="git_unavailable",
                    stage=stage,
                    error_type=type(exc).__name__,
                )

            if completed.returncode != 0:
                return result_error(
                    "Git 无法读取当前工作区变更。",
                    reason_code="git_failed",
                    stage=stage,
                    exit_code=completed.returncode,
                )
            outputs[stage] = completed.stdout

        display_outputs, truncated = _bounded_outputs(
            outputs,
            max(0, context.max_output_chars),
        )
        display = result_ok(
            "Git 变更读取成功。",
            **display_outputs,
            truncated=truncated,
        )
        if not truncated:
            return execution_result(display)
        complete = result_ok(
            "Git 变更读取成功。",
            **outputs,
            truncated=False,
        )
        return execution_result(display, complete)


def _timeout_result(stage: str, timeout_seconds: float) -> ToolResult:
    return result_error(
        "Git 变更读取超时。",
        reason_code="timeout",
        stage=stage,
        timeout_seconds=max(0.0, timeout_seconds),
    )


def _bounded_outputs(
    outputs: Mapping[str, str],
    max_chars: int,
) -> tuple[dict[str, str], bool]:
    remaining = max_chars
    bounded: dict[str, str] = {}
    truncated = False
    for stage, _ in _GIT_STAGES:
        value = outputs.get(stage, "")
        shown = value[:remaining]
        bounded[stage] = shown
        if len(shown) < len(value):
            truncated = True
        remaining = max(0, remaining - len(shown))
    return bounded, truncated
