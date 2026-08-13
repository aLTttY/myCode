from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict

from mycode.tools.base import execution_result, result_error, result_ok
from mycode.types import AgentDelegationConfig, ToolContext, ToolExecutionResult, ToolResult, ToolSpec

from .bridge import ParentRequestBridge
from .models import AgentInvocation, ChildRunSpec, TaskDetails
from .policy import ChildToolPolicy
from .runtime import AgentRoleRuntime
from .tasks import AgentTaskManager
from .waiting import EventForegroundWaiter, ForegroundWaiter


SessionSupplier = Callable[[], str]
ModelSupplier = Callable[[], str]


class AgentTool:
    manages_own_timeout = True

    def __init__(
        self,
        roles: AgentRoleRuntime,
        bridge: ParentRequestBridge,
        tasks: AgentTaskManager,
        session_supplier: SessionSupplier,
        model_supplier: ModelSupplier,
        config: AgentDelegationConfig,
        waiter: ForegroundWaiter | None = None,
    ) -> None:
        self.roles = roles
        self.bridge = bridge
        self.tasks = tasks
        self.session_supplier = session_supplier
        self.model_supplier = model_supplier
        self.config = config
        self.waiter = waiter or EventForegroundWaiter()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Agent",
            description=(
                "Delegate a task to an isolated defined or forked sub-agent. "
                + self.roles.catalog_prompt()
            ),
            parameters={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["defined", "fork"]},
                    "prompt": {"type": "string"},
                    "role": {"type": "string"},
                    "background": {"type": "boolean"},
                },
                "required": ["type", "prompt"],
                "additionalProperties": False,
            },
        )

    def run(
        self, arguments: Mapping[str, object], context: ToolContext
    ) -> ToolResult | ToolExecutionResult:
        del context
        try:
            invocation = _agent_invocation(arguments)
            session_id = self.session_supplier()
            parent = self.bridge.current(session_id)
            role = None
            if invocation.kind == "defined":
                assert invocation.role is not None
                role = self.roles.definition(invocation.role)
                model_id = (
                    self.model_supplier()
                    if role.model == "inherit"
                    else self.config.model_aliases[role.model]
                )
            else:
                model_id = self.model_supplier()
            initial_background = invocation.background or invocation.kind == "fork"
            policy = ChildToolPolicy(
                role=role,
                parent_mode=parent.mode,
                background_allowed_tools=self.config.background_allowed_tools,
            )
            task_id = "agt_" + uuid.uuid4().hex[:16]
            snapshot = self.tasks.submit(
                ChildRunSpec(
                    task_id=task_id,
                    session_id=session_id,
                    kind=invocation.kind,
                    prompt=invocation.prompt,
                    role=role,
                    model_id=model_id,
                    initial_background=initial_background,
                    parent_mode=parent.mode,
                    fork_snapshot=parent if invocation.kind == "fork" else None,
                    tool_policy=policy,
                )
            )
            if initial_background:
                return result_ok(
                    "子 Agent 已进入后台。",
                    **_task_payload(TaskDetails(snapshot)),
                )
            reason = self.waiter.wait(
                task_id,
                self.tasks.done_event(session_id, task_id),
                self.config.foreground_timeout_seconds,
            )
            settled = self.tasks.finish_foreground_wait(session_id, task_id, reason)
            message = "子 Agent 已完成。" if settled.completed else "子 Agent 正在后台继续执行。"
            return _bounded_details_result(
                message, settled.details, self.config.inbox_preview_chars
            )
        except Exception as exc:
            message = getattr(exc, "user_message", str(exc))
            return result_error(message or "无法创建子 Agent。", reason="invalid_agent_request")


class TaskTool:
    manages_own_timeout = True

    def __init__(
        self,
        tasks: AgentTaskManager,
        session_supplier: SessionSupplier,
        config: AgentDelegationConfig,
    ) -> None:
        self.tasks = tasks
        self.session_supplier = session_supplier
        self.config = config

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="Task",
            description="List, inspect, wait for, or cancel sub-agent tasks in this session.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "get", "wait", "cancel"]},
                    "task_id": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        )

    def run(
        self, arguments: Mapping[str, object], context: ToolContext
    ) -> ToolResult | ToolExecutionResult:
        del context
        try:
            unknown = set(arguments) - {"action", "task_id", "timeout_seconds"}
            if unknown:
                raise ValueError(f"Task 包含未知参数：{', '.join(sorted(unknown))}。")
            action = arguments.get("action")
            if action not in {"list", "get", "wait", "cancel"}:
                raise ValueError("Task action 必须是 list、get、wait 或 cancel。")
            session_id = self.session_supplier()
            if action == "list":
                if "task_id" in arguments or "timeout_seconds" in arguments:
                    raise ValueError("Task list 不接受 task_id 或 timeout_seconds。")
                tasks = [
                    _snapshot_payload(item)
                    for item in self.tasks.list_tasks(session_id)
                ]
                return result_ok("已列出当前会话子任务。", tasks=tasks)
            task_id = arguments.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError(f"Task {action} 必须提供非空 task_id。")
            if action == "cancel":
                if "timeout_seconds" in arguments:
                    raise ValueError("Task cancel 不接受 timeout_seconds。")
                snapshot = self.tasks.cancel_task(session_id, task_id)
                return result_ok("已处理取消请求。", task=_snapshot_payload(snapshot))
            if action == "wait":
                timeout = arguments.get(
                    "timeout_seconds", self.config.task_wait_timeout_seconds
                )
                if (
                    isinstance(timeout, bool)
                    or not isinstance(timeout, (int, float))
                    or not math.isfinite(float(timeout))
                    or not 0 < float(timeout) <= self.config.task_wait_max_seconds
                ):
                    raise ValueError(
                        "Task wait timeout_seconds 必须是配置上限内的有限正数。"
                    )
                details = self.tasks.wait_task(
                    session_id, task_id, float(timeout)
                )
            else:
                if "timeout_seconds" in arguments:
                    raise ValueError("Task get 不接受 timeout_seconds。")
                details = self.tasks.get_task(session_id, task_id)
            return _bounded_details_result(
                "已取得子任务状态。",
                details,
                self.config.inbox_preview_chars,
            )
        except Exception as exc:
            message = getattr(exc, "user_message", str(exc))
            return result_error(message or "Task 操作失败。", reason="invalid_task_request")


def _agent_invocation(arguments: Mapping[str, object]) -> AgentInvocation:
    unknown = set(arguments) - {"type", "prompt", "role", "background"}
    if unknown:
        raise ValueError(f"Agent 包含未知参数：{', '.join(sorted(unknown))}。")
    kind = arguments.get("type")
    if kind not in {"defined", "fork"}:
        raise ValueError("Agent type 必须是 defined 或 fork。")
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Agent prompt 必须是非空字符串。")
    background = arguments.get("background", False)
    if not isinstance(background, bool):
        raise ValueError("Agent background 必须是布尔值。")
    role_value = arguments.get("role")
    if kind == "defined":
        if not isinstance(role_value, str) or not role_value:
            raise ValueError("定义式 Agent 必须指定非空 role。")
        role = role_value
    else:
        if role_value is not None:
            raise ValueError("Fork Agent 不得指定 role。")
        role = None
    return AgentInvocation(kind, prompt, role, background)


def _task_payload(details: TaskDetails) -> dict[str, object]:
    data = _snapshot_payload(details.snapshot)
    data["result"] = details.result
    return data


def _snapshot_payload(snapshot) -> dict[str, object]:
    return {
        "task_id": snapshot.task_id,
        "session_id": snapshot.session_id,
        "kind": snapshot.kind,
        "role": snapshot.role,
        "status": snapshot.status,
        "delivery_mode": snapshot.delivery_mode,
        "created_at": snapshot.created_at.isoformat(),
        "started_at": snapshot.started_at.isoformat() if snapshot.started_at else None,
        "finished_at": snapshot.finished_at.isoformat() if snapshot.finished_at else None,
        "cancel_requested": snapshot.cancel_requested,
        "token_usage": asdict(snapshot.token_usage) if snapshot.token_usage else None,
        "failure_reason": snapshot.failure_reason,
    }


def _bounded_details_result(
    message: str,
    details: TaskDetails,
    limit: int,
) -> ToolExecutionResult:
    complete_payload = _task_payload(details)
    result = details.result
    if len(result) <= limit:
        return execution_result(result_ok(message, **complete_payload))
    marker = "\n…[结果已截断，请使用 Task get 查看完整结果]…\n"
    available = max(2, limit - len(marker))
    head = available // 2
    preview = result[:head] + marker + result[-(available - head):]
    display_payload = dict(complete_payload)
    display_payload["result"] = preview
    display_payload["result_truncated"] = True
    complete_payload["result_truncated"] = False
    return execution_result(
        result_ok(message, **display_payload),
        result_ok(message, **complete_payload),
    )
