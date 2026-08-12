from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from mycode.matching import MatchKind, MatchPattern


PermissionMode = Literal["strict", "default", "allow"]
RuleEffect = Literal["allow", "deny"]
RuleSource = Literal["session", "local", "project", "user"]
ApprovalChoice = Literal["deny", "allow_once", "allow_session"]


@dataclass(frozen=True)
class PermissionRule:
    tool: str
    matcher: MatchPattern
    effect: RuleEffect
    source: RuleSource

    @property
    def pattern(self) -> str:
        return self.matcher.value

    @property
    def match_type(self) -> MatchKind:
        return self.matcher.kind

    @property
    def expression(self) -> str:
        prefix = "!" if self.matcher.negated else ""
        return f"{prefix}{self.tool}({self.matcher.render()})"


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
