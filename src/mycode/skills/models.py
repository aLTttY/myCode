from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal, Mapping, Protocol, Sequence, TypeVar

from mycode.prompts.modes import DynamicInstruction
from mycode.types import Message, TokenUsage, UserFacingError

if TYPE_CHECKING:
    from mycode.agent.cancellation import CancellationToken


SkillMode = Literal["shared", "isolated"]
SkillSource = Literal["project", "user", "builtin"]
SkillInvocationOrigin = Literal["slash", "agent"]
SkillExecutionStatus = Literal["completed", "failed", "cancelled"]
SkillDiagnosticLevel = Literal["warning", "error"]

_T = TypeVar("_T")


def immutable_mapping(values: Mapping[str, _T] | None = None) -> Mapping[str, _T]:
    return MappingProxyType(dict(values or {}))


@dataclass(frozen=True)
class SkillToolDefinition:
    local_name: str
    exposed_name: str
    description: str
    parameters: Mapping[str, object]
    script_path: Path
    fingerprint: str


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    mode: SkillMode
    history: int | None
    model: str | None
    sop: str
    compiled_sop: str
    source: SkillSource
    source_id: str
    package_root: Path | None
    dedicated_tools: tuple[SkillToolDefinition, ...]
    fingerprint: str


@dataclass(frozen=True)
class SkillDiagnostic:
    level: SkillDiagnosticLevel
    code: str
    source_id: str
    message: str


@dataclass(frozen=True)
class SkillSnapshot:
    definitions: Mapping[str, SkillDefinition]
    dedicated_tools: Mapping[str, SkillToolDefinition]
    diagnostics: tuple[SkillDiagnostic, ...] = ()
    fingerprint: str = ""

    @classmethod
    def empty(cls) -> SkillSnapshot:
        return cls(definitions=immutable_mapping(), dedicated_tools=immutable_mapping())


@dataclass(frozen=True)
class ActiveSkill:
    name: str
    activated_fingerprint: str
    order: int


@dataclass(frozen=True)
class SkillInvocation:
    name: str
    input_text: str
    origin: SkillInvocationOrigin
    runtime_mode: Literal["default", "plan"]


@dataclass(frozen=True)
class IsolatedSkillResult:
    status: SkillExecutionStatus
    summary: str
    token_usage: TokenUsage | None = None


class IsolatedSkillExecutor(Protocol):
    def run(
        self,
        invocation: SkillInvocation,
        definition: SkillDefinition,
        history: Sequence[Message],
        cancellation: CancellationToken,
        *,
        dynamic_instructions: Sequence[DynamicInstruction] = (),
        on_instructions_commit: Callable[[], None] | None = None,
        on_instructions_release: Callable[[], None] | None = None,
    ) -> IsolatedSkillResult:
        ...


@dataclass(frozen=True)
class SkillActivation:
    definition: SkillDefinition
    newly_activated: bool


@dataclass(frozen=True)
class SkillRuntimeUpdate:
    deactivated: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillRefreshReport:
    snapshot: SkillSnapshot
    changed: bool
    diagnostics: tuple[SkillDiagnostic, ...] = ()


class SkillCatalogError(UserFacingError):
    pass


class SkillValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
