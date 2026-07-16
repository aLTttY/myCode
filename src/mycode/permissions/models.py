from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


PermissionMode = Literal["strict", "default", "allow"]
RuleEffect = Literal["allow", "deny"]
RuleSource = Literal["session", "local", "project", "user"]
MatchType = Literal["exact", "glob"]
ApprovalChoice = Literal["deny", "allow_once", "allow_session"]


@dataclass(frozen=True)
class PermissionRule:
    tool: str
    pattern: str
    effect: RuleEffect
    source: RuleSource
    match_type: MatchType

    @property
    def expression(self) -> str:
        return f"{self.tool}({self.pattern})"


@dataclass(frozen=True)
class PermissionLayer:
    source: RuleSource
    mode: PermissionMode | None = None
    rules: tuple[PermissionRule, ...] = ()


@dataclass(frozen=True)
class PermissionRequest:
    tool_call_id: str
    tool: str
    target: str
    arguments: Mapping[str, object]
    workspace_root: Path


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason_code: str
    message: str
    target: str
    matched_source: RuleSource | None = None
    matched_rule: PermissionRule | None = None


@dataclass(frozen=True)
class ApprovalPrompt:
    tool: str
    target: str
    reason: str


@dataclass(frozen=True)
class PermissionConfigSet:
    user: PermissionLayer
    project: PermissionLayer
    local: PermissionLayer
    effective_mode: PermissionMode


class PermissionValidationError(Exception):
    def __init__(self, reason_code: str, message: str, target: str = "") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.target = target
