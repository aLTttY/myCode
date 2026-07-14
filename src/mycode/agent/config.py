from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AgentMode = Literal["default", "plan", "do"]


@dataclass(frozen=True)
class AgentConfig:
    max_iterations: int = 8
    max_unknown_tool_calls: int = 2
    prompt_repeat_interval: int = 3


@dataclass(frozen=True)
class AgentRequest:
    text: str
    mode: AgentMode = "default"
