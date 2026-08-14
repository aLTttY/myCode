from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from mycode.teams.models import BackendDiagnostic, TeamError

from .base import BackendProbeRequest, TeamMemberBackend


@dataclass(frozen=True)
class BackendSelection:
    backend: TeamMemberBackend
    actual_backend: Literal["tmux", "coroutine"]
    diagnostics: tuple[BackendDiagnostic, ...]
    fallback_reason: str = ""


class TeamBackendSelector:
    def __init__(self, tmux: TeamMemberBackend, coroutine: TeamMemberBackend) -> None:
        self.backends = {"tmux": tmux, "coroutine": coroutine}

    def select(
        self,
        preference: Literal["auto", "tmux", "coroutine"],
        workspace: Path,
    ) -> BackendSelection:
        request = BackendProbeRequest(workspace)
        probes = {name: backend.probe(request) for name, backend in self.backends.items()}
        diagnostics = tuple(
            BackendDiagnostic(probe.backend, probe.available, probe.code, probe.message)
            for probe in probes.values()
        )
        if preference in {"tmux", "coroutine"}:
            probe = probes[preference]
            if not probe.available:
                raise TeamError("backend_unavailable", f"显式请求的 {preference} 后端不可用：{probe.message}")
            return BackendSelection(self.backends[preference], preference, diagnostics)
        if probes["tmux"].available:
            return BackendSelection(self.backends["tmux"], "tmux", diagnostics)
        if probes["coroutine"].available:
            return BackendSelection(
                self.backends["coroutine"], "coroutine", diagnostics,
                f"tmux 不可用，已明确降级为 coroutine：{probes['tmux'].message}",
            )
        raise TeamError("backend_unavailable", "tmux 与 coroutine 后端均不可用。")
