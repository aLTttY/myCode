from __future__ import annotations

from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

from mycode.agent.cancellation import CancellationToken
from mycode.agent.events import AgentEvent
from mycode.agent.tools import ToolBatch
from mycode.permissions.service import PermissionService
from mycode.tools.executor import ToolExecutor
from mycode.tools.registry import ToolRegistry
from mycode.types import ToolCall, ToolContext, ToolResult


class BatchToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolContext,
        permission_service: PermissionService | None = None,
    ) -> None:
        self.registry = registry
        self.context = context
        self.permission_service = permission_service or PermissionService.with_mode("default")

    def execute_batches(
        self,
        batches: Sequence[ToolBatch],
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent | tuple[str, ToolResult]]:
        for batch in batches:
            if cancellation.is_cancelled():
                return
            if batch.safety == "read":
                yield from self._execute_read_batch(batch.calls, cancellation)
            else:
                yield from self._execute_side_effect_batch(batch.calls, cancellation)

    def _execute_side_effect_batch(
        self,
        calls: Sequence[ToolCall],
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent | tuple[str, ToolResult]]:
        executor = ToolExecutor(self.registry, self.context, self.permission_service)
        for call in calls:
            if cancellation.is_cancelled():
                return
            yield AgentEvent(
                type="tool_call_started",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_arguments=call.arguments,
            )
            result = executor.execute(call)
            yield AgentEvent(
                type="tool_result",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_result=result,
            )
            yield (call.id, result)

    def _execute_read_batch(
        self,
        calls: Sequence[ToolCall],
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent | tuple[str, ToolResult]]:
        for call in calls:
            if cancellation.is_cancelled():
                return
            yield AgentEvent(
                type="tool_call_started",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_arguments=call.arguments,
            )

        single_executor = ToolExecutor(self.registry, self.context, self.permission_service)
        with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
            futures = {pool.submit(single_executor.execute, call): call for call in calls}
            for future in as_completed(futures):
                call = futures[future]
                if cancellation.is_cancelled():
                    return
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - agent 边界必须结构化失败。
                    result = ToolResult(ok=False, message=f"工具执行失败：{exc}", data={"tool": call.name})
                yield AgentEvent(
                    type="tool_result",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    tool_result=result,
                )
                yield (call.id, result)
