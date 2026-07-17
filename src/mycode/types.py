from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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
class AppConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig | None = None
    mcp_servers: tuple[MCPServerConfig, ...] = ()


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


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str
    data: dict[str, object]


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
