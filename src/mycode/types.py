from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol


DEFAULT_BACKGROUND_AGENT_TOOLS = (
    "read_file",
    "find_files",
    "search_code",
    "read_git_changes",
)


@dataclass(frozen=True)
class WorktreeInitRule:
    action: Literal["copy", "symlink", "hooks"]
    source: str
    target: str | None = None
    required: bool = False


DEFAULT_WORKTREE_INIT_RULES = (
    WorktreeInitRule("copy", "config.yaml", "config.yaml"),
    WorktreeInitRule(
        "copy",
        ".mycode/permissions.local.yaml",
        ".mycode/permissions.local.yaml",
    ),
    WorktreeInitRule(
        "copy",
        ".mycode/hooks.local.yaml",
        ".mycode/hooks.local.yaml",
    ),
    WorktreeInitRule("symlink", ".venv", ".venv"),
    WorktreeInitRule("hooks", ".git/hooks"),
)


@dataclass(frozen=True)
class WorktreeConfig:
    git_timeout_seconds: float = 10.0
    cleanup_interval_seconds: float = 300.0
    stale_after_seconds: float = 86_400.0
    initialization: tuple[WorktreeInitRule, ...] = DEFAULT_WORKTREE_INIT_RULES
    copy_max_files: int = 10_000
    copy_max_bytes: int = 100 * 1024 * 1024


@dataclass(frozen=True)
class AgentDelegationConfig:
    model_aliases: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    background_allowed_tools: tuple[str, ...] = DEFAULT_BACKGROUND_AGENT_TOOLS
    foreground_timeout_seconds: float = 30.0
    task_wait_timeout_seconds: float = 30.0
    task_wait_max_seconds: float = 300.0
    shutdown_timeout_seconds: float = 5.0
    max_concurrency: int = 4
    max_queue_size: int = 32
    inbox_preview_chars: int = 8_000
    worktree: WorktreeConfig = field(default_factory=WorktreeConfig)


@dataclass(frozen=True)
class VerificationCommand:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: float = 300.0


@dataclass(frozen=True)
class CoordinatorConfig:
    enabled: bool = False


@dataclass(frozen=True)
class TeamConfig:
    max_members: int = 8
    max_tasks: int = 1_000
    max_dependencies_per_task: int = 32
    max_message_chars: int = 20_000
    message_summary_chars: int = 240
    mailbox_batch_size: int = 50
    max_mailbox_bytes: int = 52_428_800
    max_context_bytes: int = 104_857_600
    max_work_log_entries: int = 1_000
    lock_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    backend_start_timeout_seconds: float = 10.0
    integration_timeout_seconds: float = 300.0
    verification_commands: tuple[VerificationCommand, ...] = ()
    coordinator: CoordinatorConfig = field(default_factory=CoordinatorConfig)


class FileReadCacheProtocol(Protocol):
    def get(self, path: Path) -> str | None:
        ...

    def put(self, path: Path, content: str) -> None:
        ...

    def invalidate(self, path: Path) -> None:
        ...

@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False
    budget_tokens: int | None = None


@dataclass(frozen=True)
class StdioMCPServerConfig:
    name: str
    transport: Literal["stdio"]
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] | None = None


@dataclass(frozen=True)
class HTTPMCPServerConfig:
    name: str
    transport: Literal["http"]
    url: str
    headers: Mapping[str, str] | None = None


MCPServerConfig = StdioMCPServerConfig | HTTPMCPServerConfig


@dataclass(frozen=True)
class ContextConfig:
    window_tokens: int
    tool_result_threshold_tokens: int = 8_000
    tool_batch_threshold_tokens: int = 16_000


@dataclass(frozen=True)
class AppConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig | None = None
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    context: ContextConfig = field(
        default_factory=lambda: ContextConfig(window_tokens=128_000)
    )
    agents: AgentDelegationConfig = field(default_factory=AgentDelegationConfig)
    teams: TeamConfig = field(default_factory=TeamConfig)


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True)
class StreamEvent:
    type: Literal[
        "text_delta",
        "message_done",
        "tool_call_delta",
        "tool_call_done",
        "tool_started",
        "tool_finished",
        "token_usage",
    ]
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    tool_result: ToolResult | None = None
    token_usage: TokenUsage | None = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_unavailable: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ToolContext:
    workspace_root: Path
    timeout_seconds: float = 10.0
    max_output_chars: int = 20_000
    file_read_cache: FileReadCacheProtocol | None = None
    process_environment: Mapping[str, str] | None = None
    excluded_roots: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str
    data: dict[str, object]


@dataclass(frozen=True)
class ToolExecutionResult:
    display: ToolResult
    complete: ToolResult

    @classmethod
    def same(cls, result: ToolResult) -> ToolExecutionResult:
        return cls(display=result, complete=result)

    @property
    def ok(self) -> bool:
        return self.display.ok

    @property
    def message(self) -> str:
        return self.display.message

    @property
    def data(self) -> dict[str, object]:
        return self.display.data


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass
class PendingToolCall:
    id: str
    name: str
    arguments_json_parts: list[str]


class UserFacingError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ConfigError(UserFacingError):
    pass


class ProviderError(UserFacingError):
    pass


class ToolError(UserFacingError):
    pass
