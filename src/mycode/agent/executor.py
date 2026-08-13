from __future__ import annotations

from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from mycode.agent.cancellation import CancellationToken
from mycode.agent.events import AgentEvent
from mycode.agent.tools import ToolBatch
from mycode.permissions.service import PermissionService
from mycode.tools.executor import ToolExecutionRecord, ToolExecutor
from mycode.tools.registry import ToolRegistry
from mycode.types import ToolCall, ToolContext, ToolExecutionResult, ToolResult

if TYPE_CHECKING:
    from mycode.agents.policy import ChildToolPolicy
    from mycode.hooks.runtime import HookRuntime


BatchResultSource = Literal["tool", "permission", "hook", "validation", "policy"]


class BatchToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolContext,
        permission_service: PermissionService | None = None,
        hook_runtime: HookRuntime | None = None,
        tool_policy: ChildToolPolicy | None = None,
        background_supplier: Callable[[], bool] | None = None,
    ) -> None:
        self.registry = registry
        self.context = context
        self.permission_service = permission_service or PermissionService.with_mode("default")
        self.hook_runtime = hook_runtime
        self.tool_policy = tool_policy
        self.background_supplier = background_supplier or (lambda: False)

    def execute_batches(
        self,
        batches: Sequence[ToolBatch],
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent | tuple[str, ToolExecutionResult]]:
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
    ) -> Iterator[AgentEvent | tuple[str, ToolExecutionResult]]:
        executor = ToolExecutor(self.registry, self.context, self.permission_service)
        for call in calls:
            if cancellation.is_cancelled():
                return
            denied = self._preflight(call)
            if denied is not None:
                result, source = denied
                yield AgentEvent(
                    type="tool_result",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    tool_result=result.display,
                )
                self._after_tool(call, result, source)
                yield (call.id, result)
                continue
            yield AgentEvent(
                type="tool_call_started",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_arguments=call.arguments,
            )
            record = executor.execute_record(call)
            result = record.result
            yield AgentEvent(
                type="tool_result",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_result=result.display,
            )
            self._after_tool(call, result, record.source)
            yield (call.id, result)

    def _execute_read_batch(
        self,
        calls: Sequence[ToolCall],
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent | tuple[str, ToolExecutionResult]]:
        results: dict[str, ToolExecutionResult] = {}
        sources: dict[str, BatchResultSource] = {}
        allowed_calls: list[ToolCall] = []
        for call in calls:
            if cancellation.is_cancelled():
                return
            denied = self._preflight(call)
            if denied is not None:
                result, source = denied
                results[call.id] = result
                sources[call.id] = source
                yield AgentEvent(
                    type="tool_result",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    tool_result=result.display,
                )
                continue
            allowed_calls.append(call)
            yield AgentEvent(
                type="tool_call_started",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_arguments=call.arguments,
            )

        single_executor = ToolExecutor(self.registry, self.context, self.permission_service)
        with ThreadPoolExecutor(max_workers=max(1, len(allowed_calls))) as pool:
            futures = {
                pool.submit(single_executor.execute_record, call): call for call in allowed_calls
            }
            for future in as_completed(futures):
                call = futures[future]
                try:
                    record = future.result()
                except Exception as exc:  # noqa: BLE001 - agent 边界必须结构化失败。
                    record = ToolExecutionRecord(
                        ToolExecutionResult.same(
                            ToolResult(
                                ok=False,
                                message=f"工具执行失败：{exc}",
                                data={"tool": call.name},
                            )
                        ),
                        "tool",
                    )
                result = record.result
                results[call.id] = result
                sources[call.id] = record.source
                yield AgentEvent(
                    type="tool_result",
                    tool_call_id=call.id,
                    tool_name=call.name,
                    tool_result=result.display,
                )
        for call in calls:
            result = results.get(call.id)
            if result is not None:
                self._after_tool(call, result, sources[call.id])
                yield (call.id, result)

    def _before_tool(self, call: ToolCall) -> str | None:
        if self.hook_runtime is None:
            return None
        try:
            decision = self.hook_runtime.before_tool(call)
        except Exception:  # noqa: BLE001 - Hook 故障必须默认放行。
            return None
        return decision.reason if decision.denied else None

    def _preflight(
        self, call: ToolCall
    ) -> tuple[ToolExecutionResult, BatchResultSource] | None:
        if self.tool_policy is not None and self.registry.contains(call.name):
            try:
                decision = self.tool_policy.authorize_call(
                    call.name, background=self.background_supplier()
                )
            except Exception:
                return _policy_denied_result(
                    call,
                    "子 Agent 工具策略发生错误，已安全拒绝。",
                    "policy_error",
                ), "policy"
            if decision is not None and not decision.allowed:
                return _policy_denied_result(
                    call, decision.message, decision.reason_code
                ), "policy"
        denied = self._before_tool(call)
        if denied is not None:
            return _hook_denied_result(call, denied), "hook"
        return None

    def _after_tool(
        self,
        call: ToolCall,
        result: ToolExecutionResult,
        source: BatchResultSource,
    ) -> None:
        if self.hook_runtime is None:
            return
        try:
            self.hook_runtime.after_tool(call, result, source)
        except Exception:  # noqa: BLE001 - Hook 故障不得覆盖工具结果。
            pass


def _hook_denied_result(call: ToolCall, reason: str) -> ToolExecutionResult:
    return ToolExecutionResult.same(
        ToolResult(
            ok=False,
            message=reason or "Hook 安全策略拒绝了该工具调用。",
            data={"tool": call.name, "hook_reason": "denied"},
        )
    )


def _policy_denied_result(
    call: ToolCall, reason: str, reason_code: str
) -> ToolExecutionResult:
    return ToolExecutionResult.same(
        ToolResult(
            ok=False,
            message=reason or "子 Agent 工具策略拒绝了该调用。",
            data={"tool": call.name, "policy_reason": reason_code},
        )
    )
