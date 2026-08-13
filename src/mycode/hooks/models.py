from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping, Union

from mycode.matching import MatchPattern
from mycode.prompts.modes import DynamicInstruction


HookEventName = Literal[
    "session_start",
    "session_end",
    "turn_start",
    "turn_end",
    "message_received",
    "message_sent",
    "tool_before",
    "tool_after",
    "context_compacted",
    "agent_error",
]
HookSource = Literal["user", "project", "local"]
HookConditionOperator = Literal["all", "any"]
HookResultSource = Literal["tool", "permission", "hook", "validation", "policy"]

HOOK_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "session_start",
        "session_end",
        "turn_start",
        "turn_end",
        "message_received",
        "message_sent",
        "tool_before",
        "tool_after",
        "context_compacted",
        "agent_error",
    }
)


@dataclass(frozen=True)
class HookClause:
    field: str
    pattern: MatchPattern


@dataclass(frozen=True)
class HookCondition:
    operator: HookConditionOperator
    clauses: tuple[HookClause, ...]


@dataclass(frozen=True)
class CommandAction:
    command: str
    timeout_seconds: float = 10.0
    once: bool = False
    asynchronous: bool = False


@dataclass(frozen=True)
class HTTPAction:
    url: str
    method: str = "POST"
    headers: Mapping[str, str] = field(default_factory=dict)
    once: bool = False
    asynchronous: bool = False


@dataclass(frozen=True)
class PromptAction:
    content: str
    once: bool = False


@dataclass(frozen=True)
class AgentAction:
    prompt: str
    once: bool = False


HookAction = Union[CommandAction, HTTPAction, PromptAction, AgentAction]


@dataclass(frozen=True)
class HookRule:
    rule_id: str
    source: HookSource
    source_path: Path
    source_index: int
    event: HookEventName
    condition: HookCondition | None
    action: HookAction


@dataclass(frozen=True)
class HookSnapshot:
    rules: tuple[HookRule, ...] = ()


class FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("Hook Payload 是只读的。")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return FrozenDict({str(key): freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    return value


@dataclass(frozen=True)
class HookEvent:
    name: HookEventName
    payload: Mapping[str, object]


HookActionStatus = Literal[
    "success",
    "failed",
    "cancelled",
    "submitted",
    "denied",
    "placeholder",
]


@dataclass(frozen=True)
class HookActionOutcome:
    status: HookActionStatus
    reason: str = ""
    code: str = ""


@dataclass(frozen=True)
class HookDispatchResult:
    denied: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HookDiagnostic:
    source_path: Path
    source_index: int
    event: HookEventName
    code: str
    message: str


@dataclass(frozen=True)
class HookPromptLease:
    lease_id: str
    instructions: tuple[DynamicInstruction, ...]


@dataclass(frozen=True)
class HookTurn:
    id: int
    mode: str
    input_kind: str
