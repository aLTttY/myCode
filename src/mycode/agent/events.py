from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mycode.types import TokenUsage, ToolResult


AgentStopReason = Literal[
    "completed",
    "max_iterations",
    "cancelled",
    "unknown_tools",
    "stream_error",
    "tool_parse_error",
]


@dataclass(frozen=True)
class AgentEvent:
    type: Literal[
        "text_delta",
        "tool_call_started",
        "tool_result",
        "token_usage",
        "progress",
        "done",
        "error",
    ]
    text: str = ""
    iteration: int = 0
    max_iterations: int = 0
    tool_call_id: str = ""
    tool_name: str = ""
    tool_result: ToolResult | None = None
    stop_reason: AgentStopReason | None = None
    message: str = ""
    token_usage: TokenUsage | None = None


def progress_event(iteration: int, max_iterations: int, message: str = "") -> AgentEvent:
    return AgentEvent(
        type="progress",
        iteration=iteration,
        max_iterations=max_iterations,
        message=message,
    )


def done_event(
    stop_reason: AgentStopReason,
    message: str = "",
    iteration: int = 0,
    max_iterations: int = 0,
) -> AgentEvent:
    return AgentEvent(
        type="done",
        stop_reason=stop_reason,
        message=message,
        iteration=iteration,
        max_iterations=max_iterations,
    )
