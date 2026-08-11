from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from threading import Event, Thread

from mycode.tools.base import result_error
from mycode.types import ToolContext, ToolResult, ToolSpec

from .models import SkillToolDefinition


class LoadSkillTool:
    def __init__(self, handler: Callable[[str], ToolResult]) -> None:
        self._handler = handler
        self._spec = ToolSpec(
            name="load_skill",
            description=(
                "按名称加载一个当前目录中的 Skill。共享模式会激活其完整 SOP 和工具白名单；"
                "独立模式会在隔离对话中执行，并把结果摘要作为工具结果返回。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的 Skill 唯一名字。",
                    }
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str) or not name.strip():
            return result_error("参数 `name` 必须是非空字符串。", reason="invalid_arguments")
        return self._handler(name.strip())


class SkillScriptTool:
    def __init__(self, definition: SkillToolDefinition) -> None:
        self.definition = definition
        self._spec = ToolSpec(
            name=definition.exposed_name,
            description=definition.description,
            parameters=dict(definition.parameters),
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        try:
            payload = json.dumps(
                {
                    "arguments": dict(arguments),
                    "context": {"workspace_root": str(context.workspace_root.resolve())},
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            return self._failure("invalid_arguments", "专属工具参数无法编码为 JSON。")

        script = self.definition.script_path
        if script.is_symlink() or not script.is_file():
            return self._failure("script_unavailable", "专属工具实现脚本当前不可用。")
        try:
            process = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=context.workspace_root,
                env={
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1",
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as exc:
            return self._failure(
                "process_start_failed",
                f"专属工具进程无法启动（{type(exc).__name__}）。",
            )

        stdout = bytearray()
        stderr = bytearray()
        overflow = Event()
        byte_limit = max(1, context.max_output_chars * 4)
        readers = (
            Thread(
                target=_read_bounded,
                args=(process.stdout, stdout, byte_limit, overflow, process),
                daemon=True,
            ),
            Thread(
                target=_read_bounded,
                args=(process.stderr, stderr, byte_limit, overflow, process),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        try:
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
            process.wait(timeout=context.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            return self._finish_failure(readers, "timeout", "专属工具执行超时。")
        except (BrokenPipeError, OSError) as exc:
            process.kill()
            process.wait()
            return self._finish_failure(
                readers,
                "stdin_failed",
                f"专属工具输入失败（{type(exc).__name__}）。",
            )
        finally:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()

        for reader in readers:
            reader.join(timeout=1.0)
        if overflow.is_set():
            return self._failure("output_too_large", "专属工具输出超过大小限制。")
        if process.returncode != 0:
            return self._failure("nonzero_exit", f"专属工具进程退出码为 {process.returncode}。")
        try:
            text = bytes(stdout).decode("utf-8")
        except UnicodeDecodeError:
            return self._failure("invalid_utf8", "专属工具 stdout 不是合法 UTF-8。")
        if len(text) > context.max_output_chars:
            return self._failure("output_too_large", "专属工具输出超过大小限制。")
        if not text.strip():
            return self._failure("empty_output", "专属工具没有返回 JSON 结果。")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return self._failure("invalid_json", "专属工具 stdout 不是单个 JSON 对象。")
        if not isinstance(value, dict) or set(value) != {"ok", "message", "data"}:
            return self._failure("invalid_result", "专属工具结果必须包含 ok、message、data。")
        ok = value.get("ok")
        message = value.get("message")
        data = value.get("data")
        if not isinstance(ok, bool) or not isinstance(message, str) or not isinstance(data, dict):
            return self._failure("invalid_result", "专属工具结果字段类型非法。")
        return ToolResult(ok=ok, message=message, data=data)

    def _finish_failure(
        self,
        readers: tuple[Thread, Thread],
        reason: str,
        message: str,
    ) -> ToolResult:
        for reader in readers:
            reader.join(timeout=1.0)
        return self._failure(reason, message)

    def _failure(self, reason: str, message: str) -> ToolResult:
        return result_error(message, tool=self.definition.exposed_name, reason=reason)


def _read_bounded(
    pipe,
    output: bytearray,
    limit: int,
    overflow: Event,
    process: subprocess.Popen,
) -> None:
    if pipe is None:
        return
    try:
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                return
            remaining = limit - len(output)
            if remaining > 0:
                output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                return
    except OSError:
        return
    finally:
        try:
            pipe.close()
        except OSError:
            pass
