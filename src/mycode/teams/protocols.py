from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, Mapping

from .models import TeamError
from .paths import validate_member_id, validate_task_id


@dataclass(frozen=True)
class TaskAssignmentPayload:
    type: Literal["task_assignment"]
    task_id: str
    task_revision: int
    assignee_id: str
    action: Literal["assigned", "changed", "cancelled"]


@dataclass(frozen=True)
class PlanApprovalRequestPayload:
    type: Literal["plan_approval_request"]
    task_id: str
    member_id: str
    plan_version: int
    plan_fingerprint: str


@dataclass(frozen=True)
class PlanDecisionPayload:
    type: Literal["plan_decision"]
    task_id: str
    member_id: str
    plan_version: int
    plan_fingerprint: str
    decision: Literal["approved", "rejected"]
    reason: str


@dataclass(frozen=True)
class TaskStatusPayload:
    type: Literal["task_status"]
    task_id: str
    member_id: str
    status: Literal["running", "blocked", "completed", "failed", "idle"]
    task_revision: int


ProtocolPayload = (
    TaskAssignmentPayload
    | PlanApprovalRequestPayload
    | PlanDecisionPayload
    | TaskStatusPayload
)


_FIELDS = {
    "task_assignment": {"type", "task_id", "task_revision", "assignee_id", "action"},
    "plan_approval_request": {"type", "task_id", "member_id", "plan_version", "plan_fingerprint"},
    "plan_decision": {"type", "task_id", "member_id", "plan_version", "plan_fingerprint", "decision", "reason"},
    "task_status": {"type", "task_id", "member_id", "status", "task_revision"},
}


def protocol_dict(payload: ProtocolPayload | Mapping[str, object] | None) -> dict[str, object] | None:
    if payload is None:
        return None
    value = asdict(payload) if hasattr(payload, "__dataclass_fields__") else dict(payload)
    kind = value.get("type")
    if kind not in _FIELDS:
        raise TeamError("unknown_protocol", "未知的团队结构化消息类型。")
    if set(value) != _FIELDS[str(kind)]:
        raise TeamError("invalid_protocol", "团队结构化消息字段不完整或包含未知字段。")
    validate_task_id(_string(value.get("task_id"), "task_id"))
    if kind == "task_assignment":
        validate_member_id(_string(value.get("assignee_id"), "assignee_id"))
        _positive_int(value.get("task_revision"), "task_revision")
        if value.get("action") not in {"assigned", "changed", "cancelled"}:
            raise TeamError("invalid_protocol", "任务指派 action 非法。")
    elif kind == "plan_approval_request":
        validate_member_id(_string(value.get("member_id"), "member_id"))
        _positive_int(value.get("plan_version"), "plan_version")
        _fingerprint(value.get("plan_fingerprint"))
    elif kind == "plan_decision":
        validate_member_id(_string(value.get("member_id"), "member_id"))
        _positive_int(value.get("plan_version"), "plan_version")
        _fingerprint(value.get("plan_fingerprint"))
        if value.get("decision") not in {"approved", "rejected"}:
            raise TeamError("invalid_protocol", "计划决定必须是 approved 或 rejected。")
        _string(value.get("reason"), "reason", allow_empty=True)
    else:
        validate_member_id(_string(value.get("member_id"), "member_id"))
        _positive_int(value.get("task_revision"), "task_revision")
        if value.get("status") not in {"running", "blocked", "completed", "failed", "idle"}:
            raise TeamError("invalid_protocol", "任务状态协议值非法。")
    return value


def _string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TeamError("invalid_protocol", f"协议字段 {label} 必须是字符串。")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise TeamError("invalid_protocol", f"协议字段 {label} 必须是正整数。")
    return value


def _fingerprint(value: object) -> str:
    text = _string(value, "plan_fingerprint")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise TeamError("invalid_protocol", "计划 fingerprint 非法。")
    return text
