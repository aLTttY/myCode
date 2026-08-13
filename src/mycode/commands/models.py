from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal

from mycode.context.models import ContextStatus
from mycode.types import TokenUsage

if TYPE_CHECKING:
    from .interfaces import CommandUI
    from .registry import CommandRegistry


CommandType = Literal["local", "ui", "prompt"]
RuntimeMode = Literal["default", "plan"]
RouteKind = Literal["empty", "exit", "plain", "command", "error"]
SessionOrigin = Literal["new", "restored"]
MemoryWorkerState = Literal["idle", "busy"]
PermissionMode = Literal["strict", "default", "allow"]
PermissionSource = Literal["session", "local", "project", "user"]
CommandOrigin = Literal["builtin", "skill"]


CommandHandler = Callable[
    ["CommandInvocation", "CommandRegistry", "CommandUI"],
    None,
]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: tuple[str, ...]
    description: str
    usage: str
    command_type: CommandType
    argument_hint: str = ""
    hidden: bool = False
    handler: CommandHandler | None = None
    origin: CommandOrigin = "builtin"
    skill_source: str = ""
    skill_mode: str = ""
    skill_history: int | None = None
    skill_model: str = ""


@dataclass(frozen=True)
class CommandInvocation:
    command: CommandSpec
    entered_name: str
    arguments: str


@dataclass(frozen=True)
class InputRoute:
    kind: RouteKind
    text: str = ""
    invocation: CommandInvocation | None = None
    message: str = ""


@dataclass(frozen=True)
class TokenStatus:
    last_usage: TokenUsage | None
    context: ContextStatus


@dataclass(frozen=True)
class SessionStatus:
    session_id: str
    message_count: int
    origin: SessionOrigin
    context: ContextStatus


@dataclass(frozen=True)
class MemoryStatus:
    project_count: int
    user_count: int
    project_index_path: Path
    user_index_path: Path
    worker_state: MemoryWorkerState
    pending_jobs: int


@dataclass(frozen=True)
class PermissionSourceStatus:
    source: PermissionSource
    path: Path | None
    loaded: bool
    rule_count: int


@dataclass(frozen=True)
class PermissionStatus:
    effective_mode: PermissionMode
    mode_source: str
    sources: tuple[PermissionSourceStatus, ...]


@dataclass(frozen=True)
class ApplicationStatus:
    mode: RuntimeMode
    provider: str
    model: str
    token: TokenStatus
    session: SessionStatus
    memory: MemoryStatus
    permission: PermissionStatus


@dataclass(frozen=True)
class AgentTaskSummary:
    task_id: str
    kind: str
    role: str | None
    status: str
    delivery_mode: str
    token_usage: TokenUsage | None
    failure_reason: str = ""
