from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Mapping

from mycode.agent.cancellation import CancellationToken
from mycode.providers.base import ChatRequest
from mycode.tools.registry import ToolRegistry
from mycode.types import TokenUsage


AgentSource = Literal["project", "user", "builtin", "plugin"]
ModelTier = Literal["inherit", "haiku", "sonnet", "opus"]
ChildPermissionMode = Literal["inherit", "default", "strict"]
AgentKind = Literal["defined", "fork"]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
TerminalTaskStatus = Literal["completed", "failed", "cancelled"]
DeliveryMode = Literal["foreground", "background"]


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    model: ModelTier
    max_iterations: int
    permission_mode: ChildPermissionMode
    system_prompt: str
    source: AgentSource
    source_id: str
    fingerprint: str


@dataclass(frozen=True)
class AgentDiagnostic:
    level: Literal["warning", "error"]
    code: str
    source_id: str
    message: str


@dataclass(frozen=True)
class AgentSnapshot:
    definitions: Mapping[str, AgentDefinition]
    diagnostics: tuple[AgentDiagnostic, ...]
    fingerprint: str

    @classmethod
    def empty(cls) -> AgentSnapshot:
        return cls(MappingProxyType({}), (), "")


@dataclass(frozen=True)
class AgentRefreshReport:
    snapshot: AgentSnapshot
    changed: bool


@dataclass(frozen=True)
class AgentInvocation:
    kind: AgentKind
    prompt: str
    role: str | None
    background: bool


@dataclass(frozen=True)
class TaskInvocation:
    action: Literal["list", "get", "wait", "cancel"]
    task_id: str | None
    timeout_seconds: float | None


@dataclass(frozen=True)
class ForkRequestSnapshot:
    session_id: str
    mode: Literal["default", "plan"]
    request: ChatRequest
    registry: ToolRegistry
    request_fingerprint: str


@dataclass(frozen=True)
class ChildRunSpec:
    task_id: str
    session_id: str
    kind: AgentKind
    prompt: str
    role: AgentDefinition | None
    model_id: str
    initial_background: bool
    parent_mode: Literal["default", "plan"]
    fork_snapshot: ForkRequestSnapshot | None
    tool_policy: object | None = None


@dataclass(frozen=True)
class PermissionAuditEntry:
    occurred_at: datetime
    tool_name: str
    allowed: bool
    reason_code: str


@dataclass(frozen=True)
class TaskOutcome:
    status: TerminalTaskStatus
    result: str = ""
    failure_reason: str = ""
    token_usage: TokenUsage | None = None
    permission_audit: tuple[PermissionAuditEntry, ...] = ()


@dataclass
class TaskRecord:
    spec: ChildRunSpec
    status: TaskStatus
    delivery_mode: DeliveryMode
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool
    outcome: TaskOutcome | None
    cancellation: CancellationToken
    done: threading.Event
    notification_attempted: bool = False


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    session_id: str
    kind: AgentKind
    role: str | None
    status: TaskStatus
    delivery_mode: DeliveryMode
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool
    token_usage: TokenUsage | None
    failure_reason: str


@dataclass(frozen=True)
class TaskDetails:
    snapshot: TaskSnapshot
    result: str = ""


@dataclass(frozen=True)
class InboxItem:
    task_id: str
    session_id: str
    kind: AgentKind
    role: str | None
    status: TerminalTaskStatus
    result_preview: str
    result_truncated: bool
    failure_reason: str
    token_usage: TokenUsage | None
    finished_at: datetime


@dataclass(frozen=True)
class ForegroundWaitResult:
    completed: bool
    details: TaskDetails


@dataclass(frozen=True)
class ShutdownReport:
    cancelled: int
    unfinished: int
