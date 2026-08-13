from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


LifecycleState = Literal["creating", "active", "retained", "cleanup_failed"]
DispositionStatus = Literal[
    "cleaned",
    "retained_changes",
    "retained_commits",
    "cleanup_failed",
]


@dataclass(frozen=True)
class InitializedPath:
    action: Literal["copy", "symlink", "hooks"]
    source: str
    target: str | None
    required: bool


@dataclass(frozen=True)
class WorktreeDiagnostic:
    level: Literal["warning", "error"]
    code: str
    rule_index: int | None
    message: str


@dataclass(frozen=True)
class InitializationResult:
    manifest: tuple[InitializedPath, ...]
    process_environment: Mapping[str, str]
    diagnostics: tuple[WorktreeDiagnostic, ...] = ()


@dataclass(frozen=True)
class WorktreeIdentity:
    schema_version: int
    repository_id: str
    task_id: str
    role_name: str
    managed_name: str
    main_workspace: Path
    worktree_path: Path
    branch_ref: str
    base_commit: str
    base_ref: str
    expected_gitdir: Path
    initialization_fingerprint: str
    initialization_manifest: tuple[InitializedPath, ...]
    lifecycle_state: LifecycleState
    created_at: datetime
    last_active_at: datetime


@dataclass(frozen=True)
class WorktreeRequest:
    task_id: str
    role_name: str
    managed_name: str
    main_workspace: Path
    repository_id: str
    base_commit: str
    base_ref: str
    branch_ref: str
    worktree_path: Path
    initialization_fingerprint: str
    created_at: datetime
    recovery_identity: WorktreeIdentity | None = None


@dataclass(frozen=True)
class WorktreeLease:
    identity: WorktreeIdentity
    workspace_root: Path
    recovered: bool
    lock_token: object
    process_environment: Mapping[str, str]
    initialization_diagnostics: tuple[WorktreeDiagnostic, ...] = ()


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class WorktreeRegistration:
    path: Path
    head: str
    branch_ref: str
    locked: bool
    gitdir: Path | None = None


@dataclass(frozen=True)
class WorktreeInspection:
    has_tracked_changes: bool
    has_untracked_changes: bool
    new_commits: tuple[str, ...]
    primary_ref: str
    delivery_refs: tuple[str, ...]
    protected_commits: tuple[str, ...]
    safe_for_task_exit: bool
    safe_for_protected_delete: bool
    retention_reason: Literal[
        "none",
        "uncommitted_changes",
        "unmerged_unpushed_commits",
        "status_unknown",
    ]


@dataclass(frozen=True)
class WorktreeDisposition:
    status: DispositionStatus
    identity: WorktreeIdentity
    inspection: WorktreeInspection | None
    reason: str


@dataclass(frozen=True)
class WorktreeTaskSummary:
    path: str
    branch: str
    base_commit: str
    status: Literal[
        "preparing",
        "active",
        "cleaned",
        "retained_changes",
        "retained_commits",
        "cleanup_failed",
    ]
    retention_reason: str = ""
    last_active_at: datetime | None = None


@dataclass(frozen=True)
class CleanupReport:
    cleaned: int
    skipped: int
    failed: int
    diagnostics: tuple[WorktreeDiagnostic, ...] = ()


class WorktreeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message

