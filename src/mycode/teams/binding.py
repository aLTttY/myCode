from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

from mycode.types import TeamConfig
from mycode.worktrees.paths import filesystem_repository_id
from mycode.worktrees.git import GitRunner
from mycode.worktrees.models import WorktreeError

from .identity import IdentityAuthority, LeadIdentity
from .models import TeamError, utc_now
from .storage import FileTeamStore


@dataclass(frozen=True)
class TeamBinding:
    session_id: str
    team_name: str
    actor: LeadIdentity
    coordinator_enabled: bool
    coordinator_reason: str
    bound_at: datetime


def coordinator_enabled(config: TeamConfig, environment: Mapping[str, str]) -> tuple[bool, str]:
    config_lock = config.coordinator.enabled
    env_lock = environment.get("MEWCODE_COORDINATOR") == "1"
    if config_lock and env_lock:
        return True, "config_and_environment_enabled"
    if not config_lock and not env_lock:
        return False, "config_and_environment_disabled"
    if not config_lock:
        return False, "config_lock_disabled"
    return False, "environment_lock_disabled"


class TeamBindingManager:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        config: TeamConfig,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.store = store
        self.authority = authority
        self.config = config
        self.environment = dict(os.environ if environment is None else environment)
        self._bindings: dict[str, TeamBinding] = {}

    def bind(self, session_id: str, team_name: str, workspace: Path | None = None) -> TeamBinding:
        if session_id in self._bindings:
            raise TeamError("session_already_bound", "当前会话已绑定小组；请使用 /team switch。")
        return self._bind(session_id, team_name, workspace)

    def switch(self, session_id: str, team_name: str, workspace: Path | None = None) -> TeamBinding:
        self._validate_target(team_name, workspace)
        self.clear(session_id)
        return self._bind(session_id, team_name, workspace)

    def current(self, session_id: str) -> TeamBinding | None:
        return self._bindings.get(session_id)

    def clear(self, session_id: str) -> None:
        current = self._bindings.pop(session_id, None)
        if current is not None:
            self.authority.revoke(current.actor)

    def clear_all(self) -> None:
        for session_id in tuple(self._bindings):
            self.clear(session_id)

    def _bind(self, session_id: str, team_name: str, workspace: Path | None) -> TeamBinding:
        team, _actual_workspace = self._validate_target(team_name, workspace)
        actor = self.authority.issue_lead(team.name, team.repository_id)
        enabled, reason = coordinator_enabled(self.config, self.environment)
        binding = TeamBinding(session_id, team.name, actor, enabled, reason, utc_now())
        self._bindings[session_id] = binding
        return binding

    def _validate_target(self, team_name: str, workspace: Path | None):
        aggregate = self.store.load(team_name)
        team = aggregate.team
        if team.status != "active":
            raise TeamError("team_not_active", "只能绑定 active 小组。")
        actual_workspace = (workspace or Path(team.workspace_root)).resolve(strict=True)
        if str(actual_workspace) != team.workspace_root:
            raise TeamError("workspace_mismatch", "当前工作区与小组创建工作区不一致。")
        if filesystem_repository_id(actual_workspace) != team.repository_id:
            raise TeamError("repository_mismatch", "当前 Git 仓库与小组仓库身份不一致。")
        try:
            _repository_id, _head, branch_ref = GitRunner().capture_repository(actual_workspace)
        except WorktreeError as exc:
            raise TeamError(exc.code, exc.user_message) from exc
        if branch_ref != team.lead_branch_ref:
            raise TeamError("lead_branch_mismatch", "当前 Lead 分支与小组记录不一致。")
        return team, actual_workspace
