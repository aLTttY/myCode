from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Literal, Mapping

from mycode.types import Message


SCHEMA_VERSION = 1
TeamStatus = Literal["active", "freezing", "archive_ready", "archived"]
MemberLifecycle = Literal[
    "provisioning",
    "offline",
    "starting",
    "running",
    "waiting_approval",
    "blocked",
    "idle",
    "stopping",
    "failed",
    "needs_attention",
]
TaskStatus = Literal[
    "pending",
    "dependency_blocked",
    "waiting_approval",
    "ready",
    "running",
    "blocked",
    "completed",
    "cancelled",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TeamError(Exception):
    def __init__(self, code: str, message: str, *, details: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.details = dict(details or {})


@dataclass(frozen=True)
class ActorRef:
    kind: Literal["lead", "member", "system"]
    name: str
    member_id: str | None = None


SYSTEM_ACTOR = ActorRef("system", "system")


@dataclass(frozen=True)
class BackendDiagnostic:
    backend: Literal["tmux", "coroutine"]
    available: bool
    code: str
    message: str


@dataclass(frozen=True)
class AgentRoleSnapshot:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    denied_tools: tuple[str, ...]
    model: Literal["inherit", "haiku", "sonnet", "opus"]
    max_iterations: int
    permission_mode: Literal["inherit", "default", "strict"]
    system_prompt: str
    source: Literal["project", "user", "builtin", "plugin"]
    source_id: str
    fingerprint: str
    isolation: Literal["shared", "worktree"]


@dataclass(frozen=True)
class MemberProcessIdentity:
    backend: Literal["tmux", "coroutine"]
    runtime_token: str = ""
    tmux_socket: str = ""
    tmux_session: str = ""
    tmux_window: str = ""
    tmux_pane: str = ""
    pane_pid: int | None = None


@dataclass(frozen=True)
class TeamWorktreeIdentity:
    schema_version: int
    repository_id: str
    team_name: str
    member_id: str
    managed_name: str
    main_workspace: str
    worktree_path: str
    branch_ref: str
    base_commit: str
    integrated_commit: str
    expected_gitdir: str
    initialization_fingerprint: str
    lifecycle_state: Literal["creating", "active", "retained", "cleanup_failed"]
    created_at: datetime
    last_active_at: datetime


@dataclass(frozen=True)
class TeamMemberSnapshot:
    member_id: str
    name: str
    revision: int
    role: AgentRoleSnapshot
    writable: bool
    approval_required: bool
    backend_preference: Literal["auto", "tmux", "coroutine"]
    actual_backend: Literal["tmux", "coroutine"] | None
    backend_diagnostics: tuple[BackendDiagnostic, ...]
    lifecycle: MemberLifecycle
    current_task_id: str | None
    worktree: TeamWorktreeIdentity | None
    process: MemberProcessIdentity | None
    mailbox_cursor: int
    context_sequence: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TeamSnapshot:
    schema_version: int
    revision: int
    name: str
    status: TeamStatus
    lead_name: str
    repository_id: str
    workspace_root: str
    lead_branch_ref: str
    created_at: datetime
    updated_at: datetime
    members: Mapping[str, TeamMemberSnapshot] = field(
        default_factory=lambda: MappingProxyType({})
    )
    last_transaction_id: str = ""


@dataclass(frozen=True)
class TaskWorkEntry:
    timestamp: datetime
    actor: ActorRef
    summary: str


@dataclass(frozen=True)
class SharedTaskRecord:
    task_id: str
    revision: int
    title: str
    description: str
    status: TaskStatus
    assignee_id: str | None
    dependency_ids: tuple[str, ...]
    creator: ActorRef
    work_log: tuple[TaskWorkEntry, ...]
    plan_version: int | None
    result_commit: str | None
    integrated_by: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MailboxMessage:
    schema_version: int
    record_type: Literal["message"]
    sequence: int
    message_id: str
    sender: ActorRef
    body: str
    timestamp: datetime
    read: Literal[False]
    summary: str
    protocol: Mapping[str, object] | None
    idempotency_key: str


@dataclass(frozen=True)
class MailboxAck:
    schema_version: int
    record_type: Literal["ack"]
    sequence: int
    message_id: str
    reader: ActorRef
    timestamp: datetime


MailboxRecord = MailboxMessage | MailboxAck


@dataclass(frozen=True)
class MailboxMessageView:
    message: MailboxMessage
    read: bool


@dataclass(frozen=True)
class ApprovalRecord:
    task_id: str
    member_id: str
    plan_version: int
    plan_fingerprint: str
    plan_body: str
    status: Literal["pending", "approved", "rejected", "superseded"]
    requested_at: datetime
    decided_at: datetime | None
    decided_by: ActorRef | None
    reason: str
    decision_message_id: str | None


@dataclass(frozen=True)
class MemberContextRecord:
    schema_version: int
    sequence: int
    timestamp: datetime
    message: Message
    source_message_ids: tuple[str, ...]


@dataclass(frozen=True)
class VerificationResult:
    command_id: str
    returncode: int
    summary: str
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True)
class IntegrationRecord:
    integration_id: str
    revision: int
    status: Literal[
        "preparing",
        "merging",
        "validating",
        "ready_to_advance",
        "advancing",
        "completed",
        "conflicted",
        "failed",
        "aborted",
    ]
    lead_branch_ref: str
    base_commit: str
    task_ids: tuple[str, ...]
    member_commits: Mapping[str, tuple[str, ...]]
    integration_branch_ref: str
    integration_worktree: str
    merged_commit: str | None
    verification_results: tuple[VerificationResult, ...]
    conflict_paths: tuple[str, ...]
    failure_reason: str
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class AuditEvent:
    schema_version: int
    event_id: str
    transaction_id: str
    timestamp: datetime
    actor: ActorRef
    action: str
    object_type: str
    object_id: str
    outcome: Literal["intent", "committed", "rejected", "failed"]
    reason_code: str
    summary: str


@dataclass(frozen=True)
class TeamAggregate:
    team: TeamSnapshot
    tasks: Mapping[str, SharedTaskRecord] = field(default_factory=lambda: MappingProxyType({}))
    approvals: Mapping[str, ApprovalRecord] = field(default_factory=lambda: MappingProxyType({}))
    integrations: Mapping[str, IntegrationRecord] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True)
class RevisionSet:
    team: int | None = None
    tasks: int | None = None
    approvals: int | None = None
    integrations: int | None = None


@dataclass(frozen=True)
class TeamCreateRequest:
    name: str
    repository_id: str
    workspace_root: str
    lead_branch_ref: str


@dataclass(frozen=True)
class MemberCreateRequest:
    name: str
    role: AgentRoleSnapshot
    writable: bool = True
    approval_required: bool = False
    backend_preference: Literal["auto", "tmux", "coroutine"] = "auto"


@dataclass(frozen=True)
class TaskCreateRequest:
    title: str
    description: str = ""
    assignee_id: str | None = None
    dependency_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliveryResult:
    message_id: str
    recipient: str
    sequence: int
    warning: str = ""


@dataclass(frozen=True)
class BroadcastResult:
    deliveries: tuple[DeliveryResult, ...]


@dataclass(frozen=True)
class AckResult:
    acknowledged: tuple[str, ...]


@dataclass(frozen=True)
class MailboxLease:
    lease_id: str
    messages: tuple[MailboxMessageView, ...]
