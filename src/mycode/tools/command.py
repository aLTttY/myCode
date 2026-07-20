from __future__ import annotations

import subprocess
from collections.abc import Mapping

from mycode.tools.base import execution_result, optional_float, require_str, result_error, result_ok, truncate_text
from mycode.types import ToolContext, ToolError, ToolExecutionResult, ToolResult, ToolSpec


class RunCommandTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_command",
            description="Run a shell command in the workspace and return exit code, stdout, and stderr.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout_seconds": {"type": "number", "description": "Optional timeout, capped by runtime limit."},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult | ToolExecutionResult:
        try:
            command = require_str(arguments, "command")
            timeout = min(optional_float(arguments, "timeout_seconds", context.timeout_seconds), context.timeout_seconds)
            completed = subprocess.run(
                command,
                cwd=context.workspace_root,
                shell=True,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            full_stdout = completed.stdout
            full_stderr = completed.stderr
            stdout, stdout_truncated = truncate_text(full_stdout, context.max_output_chars)
            stderr, stderr_truncated = truncate_text(full_stderr, context.max_output_chars)
            data = {
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
            }
            complete_data = {
                "exit_code": completed.returncode,
                "stdout": full_stdout,
                "stderr": full_stderr,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
            if completed.returncode == 0:
                display = result_ok("命令执行成功。", **data)
                complete = result_ok("命令执行成功。", **complete_data)
            else:
                display = result_error(f"命令退出码为 {completed.returncode}。", **data)
                complete = result_error(f"命令退出码为 {completed.returncode}。", **complete_data)
            if not stdout_truncated and not stderr_truncated:
                return execution_result(display)
            return execution_result(display, complete)
        except ToolError as exc:
            return result_error(exc.user_message)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            full_stdout = stdout
            full_stderr = stderr
            stdout, stdout_truncated = truncate_text(full_stdout, context.max_output_chars)
            stderr, stderr_truncated = truncate_text(full_stderr, context.max_output_chars)
            display = result_error(
                "命令执行超时。",
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                timeout_seconds=exc.timeout,
            )
            if not stdout_truncated and not stderr_truncated:
                return execution_result(display)
            complete = result_error(
                "命令执行超时。",
                exit_code=None,
                stdout=full_stdout,
                stderr=full_stderr,
                stdout_truncated=False,
                stderr_truncated=False,
                timeout_seconds=exc.timeout,
            )
            return execution_result(display, complete)
        except OSError as exc:
            return result_error(f"执行命令失败：{exc}")
