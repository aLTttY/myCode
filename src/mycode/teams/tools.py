from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime

from mycode.tools.base import result_error, result_ok
from mycode.tools.registry import ToolRegistry
from mycode.types import ToolContext, ToolResult, ToolSpec

from .binding import TeamBinding
from .approvals import ApprovalService
from .coordinator import CoordinatorCommandPolicy
from .identity import LeadIdentity, MemberIdentity
from .integration import IntegrationPlan, IntegrationService
from .mailbox import MailboxService
from .models import AgentRoleSnapshot, MemberCreateRequest, TaskCreateRequest, TeamError
from .service import TeamService
from .tasks import SharedTaskService
from .protocols import TaskAssignmentPayload, TaskStatusPayload


def _payload(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _payload(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _payload(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_payload(item) for item in value]
    return value


def _error(exc: Exception) -> ToolResult:
    return result_error(
        getattr(exc, "user_message", str(exc)) or "团队操作失败。",
        reason_code=getattr(exc, "code", "team_operation_failed"),
    )


class LeadTeamMemberTool:
    def __init__(
        self,
        service: TeamService,
        identity: LeadIdentity,
        role_resolver: Callable[[str], AgentRoleSnapshot],
        *,
        readonly: bool = False,
    ) -> None:
        self.service = service
        self.identity = identity
        self.role_resolver = role_resolver
        self.readonly = readonly

    @property
    def spec(self) -> ToolSpec:
        actions = ["status"] if self.readonly else ["status", "add", "upgrade", "start", "stop"]
        return ToolSpec("TeamMember", "Manage persistent team members.", {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": actions},
                "member_id": {"type": "string"}, "name": {"type": "string"},
                "role": {"type": "string"}, "writable": {"type": "boolean"},
                "approval_required": {"type": "boolean"},
                "backend": {"type": "string", "enum": ["auto", "tmux", "coroutine"]},
                "expected_revision": {"type": "integer"},
            },
            "required": ["action"], "additionalProperties": False,
        })

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        del context
        try:
            action = arguments.get("action")
            if action == "status":
                return result_ok("已取得团队状态。", team=_payload(self.service.status(self.identity)))
            if self.readonly:
                raise TeamError("readonly_mode", "Plan 模式下 TeamMember 只允许 status。")
            if action == "add":
                name = _str(arguments, "name")
                role_name = _str(arguments, "role")
                backend = arguments.get("backend", "auto")
                if backend not in {"auto", "tmux", "coroutine"}:
                    raise TeamError("invalid_backend", "backend 必须是 auto、tmux 或 coroutine。")
                member = self.service.add_member(self.identity, MemberCreateRequest(
                    name, self.role_resolver(role_name), _bool(arguments, "writable", True),
                    _bool(arguments, "approval_required", False), backend,  # type: ignore[arg-type]
                ))
                return result_ok("团队成员已创建。", member=_payload(member))
            member_id = _str(arguments, "member_id")
            if action == "start":
                return result_ok("已处理成员启动请求。", result=_payload(self.service.start_member(self.identity, member_id)))
            if action == "stop":
                return result_ok("已处理成员停止请求。", result=_payload(self.service.stop_member(self.identity, member_id)))
            if action == "upgrade":
                member = self.service.upgrade_member(
                    self.identity, member_id, self.role_resolver(_str(arguments, "role")),
                    _int(arguments, "expected_revision"),
                )
                return result_ok("成员角色快照已升级。", member=_payload(member))
            raise TeamError("invalid_action", "未知 TeamMember action。")
        except Exception as exc:
            return _error(exc)


class LeadSharedTaskTool:
    def __init__(self, service: SharedTaskService, approvals: ApprovalService, mailbox: MailboxService, identity: LeadIdentity, *, readonly: bool = False) -> None:
        self.service, self.approvals, self.mailbox, self.identity, self.readonly = service, approvals, mailbox, identity, readonly

    @property
    def spec(self) -> ToolSpec:
        actions = ["list", "get"] if self.readonly else [
            "list", "get", "create", "update", "assign", "set_dependencies",
            "start_ready", "cancel", "delete", "approve_plan", "reject_plan",
        ]
        return _task_spec(actions)

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        del context
        try:
            action = arguments.get("action")
            if action == "list":
                return result_ok("已列出共享任务。", tasks=_payload(self.service.list_tasks(self.identity)))
            if action == "get":
                return result_ok("已取得共享任务。", task=_payload(self.service.get_task(self.identity, _str(arguments, "task_id"))))
            if self.readonly:
                raise TeamError("readonly_mode", "Plan 模式下 SharedTask 只允许读取。")
            if action == "create":
                task = self.service.create_task(self.identity, TaskCreateRequest(
                    _str(arguments, "title"), str(arguments.get("description", "")),
                    arguments.get("assignee_id") if isinstance(arguments.get("assignee_id"), str) else None,
                    _strings(arguments.get("dependency_ids", []), "dependency_ids"),
                ))
            elif action == "update":
                task = self.service.update(
                    self.identity, _str(arguments, "task_id"), expected_revision=_int(arguments, "expected_revision"),
                    title=arguments.get("title") if isinstance(arguments.get("title"), str) else None,
                    description=arguments.get("description") if isinstance(arguments.get("description"), str) else None,
                )
            elif action == "assign":
                task = self.service.assign(
                    self.identity, _str(arguments, "task_id"), _str(arguments, "assignee_id"),
                    _int(arguments, "expected_revision"),
                )
            elif action == "set_dependencies":
                task = self.service.set_dependencies(
                    self.identity, _str(arguments, "task_id"),
                    _strings(arguments.get("dependency_ids", []), "dependency_ids"),
                    _int(arguments, "expected_revision"),
                )
            elif action == "start_ready":
                return result_ok("已列出可启动任务。", tasks=_payload(self.service.start_ready(
                    self.identity, _strings(arguments.get("task_ids", []), "task_ids")
                )))
            elif action == "cancel":
                task = self.service.cancel(self.identity, _str(arguments, "task_id"), _int(arguments, "expected_revision"))
            elif action == "delete":
                task = self.service.delete(self.identity, _str(arguments, "task_id"), _int(arguments, "expected_revision"))
            elif action in {"approve_plan", "reject_plan"}:
                result = self.approvals.decide(
                    self.identity, _str(arguments, "task_id"), _str(arguments, "member_id"),
                    _int(arguments, "plan_version"),
                    "approved" if action == "approve_plan" else "rejected",
                    str(arguments.get("reason", "")),
                    plan_fingerprint=_str(arguments, "plan_fingerprint"),
                )
                return result_ok("计划审批决定已持久化并通知成员。", approval=_payload(result))
            else:
                raise TeamError("invalid_action", "未知 SharedTask action。")
            if action in {"create", "assign", "update", "set_dependencies", "cancel"} and task.assignee_id is not None:
                member = self.service.store.load(self.identity.team_name).team.members[task.assignee_id]
                protocol_action = "cancelled" if action == "cancel" else ("assigned" if action in {"create", "assign"} else "changed")
                self.mailbox.send(
                    self.identity, member.name, f"共享任务 {task.task_id} 已{protocol_action}。",
                    TaskAssignmentPayload(
                        "task_assignment", task.task_id, task.revision,
                        task.assignee_id, protocol_action,  # type: ignore[arg-type]
                    ),
                    f"task-assignment:{task.task_id}:{task.revision}:{protocol_action}",
                )
            return result_ok("共享任务操作完成。", task=_payload(task))
        except Exception as exc:
            return _error(exc)


class MemberSharedTaskTool:
    def __init__(self, service: SharedTaskService, approvals: ApprovalService, mailbox: MailboxService, identity: MemberIdentity) -> None:
        self.service, self.approvals, self.mailbox, self.identity = service, approvals, mailbox, identity

    @property
    def spec(self) -> ToolSpec:
        return _task_spec(["list", "get", "create", "update_own", "start", "complete", "submit_plan"])

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        del context
        try:
            action = arguments.get("action")
            if action == "list":
                value = self.service.list_tasks(self.identity)
            elif action == "get":
                value = self.service.get_task(self.identity, _str(arguments, "task_id"))
            elif action == "create":
                value = self.service.create_task(self.identity, TaskCreateRequest(
                    _str(arguments, "title"), str(arguments.get("description", "")), None,
                    _strings(arguments.get("dependency_ids", []), "dependency_ids"),
                ))
            elif action == "update_own":
                value = self.service.update_own(
                    self.identity, _str(arguments, "task_id"), expected_revision=_int(arguments, "expected_revision"),
                    status=arguments.get("status") if isinstance(arguments.get("status"), str) else None,
                    work_log=arguments.get("work_log") if isinstance(arguments.get("work_log"), str) else None,
                )
            elif action == "start":
                value = self.service.request_start(self.identity, _str(arguments, "task_id"), _int(arguments, "expected_revision"))
            elif action == "complete":
                value = self.service.complete(
                    self.identity, _str(arguments, "task_id"), _str(arguments, "work_log"),
                    _int(arguments, "expected_revision"),
                    result_commit=arguments.get("result_commit") if isinstance(arguments.get("result_commit"), str) else None,
                )
            elif action == "submit_plan":
                value = self.approvals.submit_plan(
                    self.identity, _str(arguments, "task_id"), _str(arguments, "plan_body"),
                    _int(arguments, "expected_revision"),
                )
            else:
                raise TeamError("invalid_action", "未知成员 SharedTask action。")
            if action in {"start", "complete", "update_own"} and hasattr(value, "task_id"):
                status = "completed" if action == "complete" else getattr(value, "status", "running")
                protocol_status = status if status in {"running", "blocked", "completed"} else "running"
                self.mailbox.send(
                    self.identity, "lead", f"任务 {value.task_id} 状态更新为 {status}。",
                    TaskStatusPayload(
                        "task_status", value.task_id, self.identity.member_id,
                        protocol_status, value.revision,  # type: ignore[arg-type]
                    ),
                    f"task-status:{value.task_id}:{value.revision}:{status}",
                )
            return result_ok("共享任务操作完成。", result=_payload(value))
        except Exception as exc:
            return _error(exc)


def _task_spec(actions: list[str]) -> ToolSpec:
    return ToolSpec("SharedTask", "Read or update the persistent shared task DAG.", {
        "type": "object", "properties": {
            "action": {"type": "string", "enum": actions}, "task_id": {"type": "string"},
            "task_ids": {"type": "array", "items": {"type": "string"}},
            "title": {"type": "string"}, "description": {"type": "string"},
            "assignee_id": {"type": "string"},
            "dependency_ids": {"type": "array", "items": {"type": "string"}},
            "expected_revision": {"type": "integer"}, "status": {"type": "string"},
            "work_log": {"type": "string"}, "result_commit": {"type": "string"},
            "member_id": {"type": "string"}, "plan_version": {"type": "integer"},
            "plan_fingerprint": {"type": "string"}, "plan_body": {"type": "string"},
            "reason": {"type": "string"},
        }, "required": ["action"], "additionalProperties": False,
    })


class MailboxTool:
    def __init__(self, service: MailboxService, identity: LeadIdentity | MemberIdentity, *, readonly: bool = False) -> None:
        self.service, self.identity, self.readonly = service, identity, readonly

    @property
    def spec(self) -> ToolSpec:
        actions = ["list", "get"] if self.readonly else ["list", "get", "send", "broadcast", "ack"]
        return ToolSpec("Mailbox", "Send direct/broadcast team messages or read this actor's mailbox.", {
            "type": "object", "properties": {
                "action": {"type": "string", "enum": actions}, "recipient": {"type": "string"},
                "body": {"type": "string"}, "message_id": {"type": "string"},
                "message_ids": {"type": "array", "items": {"type": "string"}},
                "unread_only": {"type": "boolean"}, "idempotency_key": {"type": "string"},
                "protocol": {"type": "object"},
            }, "required": ["action"], "additionalProperties": False,
        })

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        del context
        try:
            action = arguments.get("action")
            if action == "list":
                result = self.service.list_messages(self.identity, _bool(arguments, "unread_only", True))
            elif action == "get":
                result = self.service.get_message(self.identity, _str(arguments, "message_id"))
            elif self.readonly:
                raise TeamError("readonly_mode", "Plan 模式下 Mailbox 只允许读取。")
            elif action == "send":
                result = self.service.send(
                    self.identity, _str(arguments, "recipient"), _str(arguments, "body"),
                    arguments.get("protocol") if isinstance(arguments.get("protocol"), dict) else None,
                    arguments.get("idempotency_key") if isinstance(arguments.get("idempotency_key"), str) else None,
                )
            elif action == "broadcast":
                result = self.service.broadcast(
                    self.identity, _str(arguments, "body"),
                    arguments.get("protocol") if isinstance(arguments.get("protocol"), dict) else None,
                    arguments.get("idempotency_key") if isinstance(arguments.get("idempotency_key"), str) else None,
                )
            elif action == "ack":
                result = self.service.ack(self.identity, list(_strings(arguments.get("message_ids", []), "message_ids")))
            else:
                raise TeamError("invalid_action", "未知 Mailbox action。")
            return result_ok("邮箱操作完成。", result=_payload(result))
        except Exception as exc:
            return _error(exc)


class TeamIntegrateTool:
    def __init__(self, service: IntegrationService, identity: LeadIdentity, *, readonly: bool = False) -> None:
        self.service, self.identity, self.readonly = service, identity, readonly
        self._plans: dict[str, IntegrationPlan] = {}

    @property
    def spec(self) -> ToolSpec:
        actions = ["preflight", "get"] if self.readonly else ["preflight", "start", "get", "abort"]
        return ToolSpec("TeamIntegrate", "Preflight and atomically integrate completed team tasks.", {
            "type": "object", "properties": {
                "action": {"type": "string", "enum": actions},
                "task_ids": {"type": "array", "items": {"type": "string"}},
                "plan_id": {"type": "string"}, "integration_id": {"type": "string"},
            }, "required": ["action"], "additionalProperties": False,
        })

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        del context
        try:
            action = arguments.get("action")
            if action == "preflight":
                plan = self.service.preflight(self.identity, _strings(arguments.get("task_ids", []), "task_ids"))
                plan_id = f"plan_{secrets.token_hex(12)}"
                self._plans[plan_id] = plan
                return result_ok("集成预检通过。", plan_id=plan_id, plan=_payload(plan))
            if action == "get":
                result = self.service.get(self.identity, _str(arguments, "integration_id"))
            elif self.readonly:
                raise TeamError("readonly_mode", "Plan 模式下不能修改集成状态。")
            elif action == "start":
                plan_id = _str(arguments, "plan_id")
                plan = self._plans.pop(plan_id, None)
                if plan is None:
                    raise TeamError("integration_plan_not_found", "集成计划不存在或已消费。")
                result = self.service.start(self.identity, plan)
            elif action == "abort":
                result = self.service.abort(self.identity, _str(arguments, "integration_id"))
            else:
                raise TeamError("invalid_action", "未知 TeamIntegrate action。")
            return result_ok("集成操作完成。", result=_payload(result))
        except Exception as exc:
            return _error(exc)


class CoordinatorCommandTool:
    def __init__(self, policy: CoordinatorCommandPolicy, binding: TeamBinding) -> None:
        self.policy, self.binding = policy, binding

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec("CoordinatorCommand", "Run a restricted read, configured verification, or scoped integration Git operation.", {
            "type": "object", "properties": {
                "action": {"type": "string", "enum": ["run", "verify", "git"]},
                "argv": {"type": "array", "items": {"type": "string"}},
                "command_id": {"type": "string"}, "integration_id": {"type": "string"},
                "operation": {"type": "string"},
            }, "required": ["action"], "additionalProperties": False,
        })

    def run(self, arguments: Mapping[str, object], context: ToolContext):
        try:
            action = arguments.get("action")
            if action == "run":
                return self.policy.execute(self.policy.validate_read(_strings(arguments.get("argv", []), "argv"), self.binding), context)
            if action == "verify":
                return self.policy.execute(self.policy.resolve_verification(_str(arguments, "command_id"), self.binding), context)
            if action == "git":
                decision = self.policy.resolve_git_operation(
                    _str(arguments, "integration_id"), _str(arguments, "operation"), self.binding
                )
                result = self.policy.scoped_git.execute(self.binding.actor, decision.integration_id, decision.operation)
                return result_ok("受限 Git operation 完成。", result=_payload(result))
            raise TeamError("invalid_action", "未知 CoordinatorCommand action。")
        except Exception as exc:
            return _error(exc)


class TeamToolRegistryProvider:
    def __init__(
        self,
        team_service: TeamService,
        task_service: SharedTaskService,
        mailbox_service: MailboxService,
        approval_service: ApprovalService,
        integration_service: IntegrationService,
        role_resolver: Callable[[str], AgentRoleSnapshot],
        coordinator_policy: CoordinatorCommandPolicy,
    ) -> None:
        self.team_service = team_service
        self.task_service = task_service
        self.mailbox_service = mailbox_service
        self.approval_service = approval_service
        self.integration_service = integration_service
        self.role_resolver = role_resolver
        self.coordinator_policy = coordinator_policy

    def for_lead(self, base: ToolRegistry, binding: TeamBinding, mode: str) -> ToolRegistry:
        readonly = mode == "plan"
        registry = base
        if binding.coordinator_enabled:
            registry = registry.exclude({"write_file", "edit_file", "run_command"})
        team = ToolRegistry()
        team.register(LeadTeamMemberTool(self.team_service, binding.actor, self.role_resolver, readonly=readonly))
        team.register(LeadSharedTaskTool(self.task_service, self.approval_service, self.mailbox_service, binding.actor, readonly=readonly))
        team.register(MailboxTool(self.mailbox_service, binding.actor, readonly=readonly))
        team.register(TeamIntegrateTool(self.integration_service, binding.actor, readonly=readonly))
        if binding.coordinator_enabled:
            team.register(CoordinatorCommandTool(self.coordinator_policy, binding))
        return registry.merge(team)

    def for_member(self, base: ToolRegistry, identity: MemberIdentity, allowed_names: tuple[str, ...]) -> ToolRegistry:
        registry = base.subset(name for name in allowed_names if base.contains(name))
        team = ToolRegistry()
        team.register(MemberSharedTaskTool(self.task_service, self.approval_service, self.mailbox_service, identity))
        team.register(MailboxTool(self.mailbox_service, identity))
        return registry.merge(team)


LeadMailboxTool = MailboxTool
MemberMailboxTool = MailboxTool


def _str(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise TeamError("invalid_argument", f"参数 {key} 必须是非空字符串。")
    return value


def _int(arguments: Mapping[str, object], key: str) -> int:
    value = arguments.get(key)
    if type(value) is not int or value <= 0:
        raise TeamError("invalid_argument", f"参数 {key} 必须是正整数。")
    return value


def _bool(arguments: Mapping[str, object], key: str, default: bool) -> bool:
    value = arguments.get(key, default)
    if type(value) is not bool:
        raise TeamError("invalid_argument", f"参数 {key} 必须是布尔值。")
    return value


def _strings(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise TeamError("invalid_argument", f"参数 {key} 必须是字符串列表。")
    return tuple(value)
