from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError

from mycode.tools.registry import ToolRegistry
from mycode.types import ToolCall, ToolContext, ToolError, ToolResult


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, context: ToolContext) -> None:
        self.registry = registry
        self.context = context

    def execute(self, call: ToolCall) -> ToolResult:
        try:
            tool = self.registry.get(call.name)
        except ToolError as exc:
            return ToolResult(ok=False, message=exc.user_message, data={"tool": call.name})

        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(tool.run, call.arguments, self.context)
            try:
                result = future.result(timeout=self.context.timeout_seconds)
            except TimeoutError:
                executor.shutdown(wait=False, cancel_futures=True)
                return ToolResult(ok=False, message="工具执行超时。", data={"tool": call.name})
            except Exception:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)
                return result
        except TimeoutError:
            return ToolResult(ok=False, message="工具执行超时。", data={"tool": call.name})
        except Exception as exc:  # noqa: BLE001 - 工具边界必须结构化失败。
            return ToolResult(ok=False, message=f"工具执行失败：{exc}", data={"tool": call.name})
