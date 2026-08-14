from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from mycode.teams.models import MemberProcessIdentity, TeamMemberSnapshot


@dataclass(frozen=True)
class BackendProbeRequest:
    workspace: Path


@dataclass(frozen=True)
class BackendProbeResult:
    backend: Literal["tmux", "coroutine"]
    available: bool
    code: str
    message: str


@dataclass(frozen=True)
class BackendStartResult:
    started: bool
    backend: Literal["tmux", "coroutine"]
    process: MemberProcessIdentity | None
    message: str


@dataclass(frozen=True)
class BackendWakeResult:
    delivered: bool
    message: str = ""


@dataclass(frozen=True)
class MemberStopResult:
    stopped: bool
    message: str = ""


@dataclass(frozen=True)
class BackendStatus:
    running: bool
    message: str = ""


class TeamMemberBackend(Protocol):
    name: Literal["tmux", "coroutine"]
    def probe(self, request: BackendProbeRequest) -> BackendProbeResult: ...
    def start(self, member: TeamMemberSnapshot) -> BackendStartResult: ...
    def wake(self, member: TeamMemberSnapshot, message_id: str) -> BackendWakeResult: ...
    def stop(self, member: TeamMemberSnapshot, timeout_seconds: float) -> MemberStopResult: ...
    def inspect(self, member: TeamMemberSnapshot) -> BackendStatus: ...
