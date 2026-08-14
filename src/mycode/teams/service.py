from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from mycode.types import TeamConfig, WorktreeConfig
from mycode.worktrees.git import GitRunner
from mycode.worktrees.models import WorktreeError
from mycode.worktrees.identity import initialization_fingerprint

from .identity import IdentityAuthority, LeadIdentity
from .models import (
    MemberCreateRequest,
    RevisionSet,
    TeamAggregate,
    TeamCreateRequest,
    TeamError,
    TeamMemberSnapshot,
    TeamSnapshot,
    utc_now,
)
from .storage import FileTeamStore
from .worktrees import TeamWorktreeManager


@dataclass(frozen=True)
class TeamActorContext:
    workspace_root: Path


@dataclass(frozen=True)
class ArchiveReadiness:
    ready: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class ArchiveResult:
    path: Path


class BackendController(Protocol):
    def start_member(self, member: TeamMemberSnapshot) -> object: ...
    def stop_member(self, member: TeamMemberSnapshot) -> object: ...


class TeamService:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        config: TeamConfig | None = None,
        *,
        git: GitRunner | None = None,
        worktrees: TeamWorktreeManager | None = None,
        backend: BackendController | None = None,
    ) -> None:
        self.store = store
        self.authority = authority
        self.config = config or store.config
        self.git = git or GitRunner()
        self.worktrees = worktrees or TeamWorktreeManager(git=self.git)
        self.backend = backend

    def create_team(self, name: str, actor_context: TeamActorContext | Path) -> TeamSnapshot:
        workspace = actor_context.workspace_root if isinstance(actor_context, TeamActorContext) else actor_context
        workspace = workspace.resolve(strict=True)
        try:
            repository_id, _head, branch_ref = self.git.capture_repository(workspace)
        except WorktreeError as exc:
            raise TeamError(exc.code, exc.user_message) from exc
        return self.store.create(TeamCreateRequest(name, repository_id, str(workspace), branch_ref))

    def resume_team(self, name: str, actor_context: TeamActorContext | Path) -> TeamSnapshot:
        workspace = actor_context.workspace_root if isinstance(actor_context, TeamActorContext) else actor_context
        aggregate = self.store.load(name)
        try:
            repository_id, _head, branch_ref = self.git.capture_repository(workspace.resolve(strict=True))
        except WorktreeError as exc:
            raise TeamError(exc.code, exc.user_message) from exc
        if aggregate.team.repository_id != repository_id or aggregate.team.workspace_root != str(workspace.resolve()):
            raise TeamError("repository_mismatch", "当前仓库与持久化小组不匹配。")
        if aggregate.team.lead_branch_ref != branch_ref:
            raise TeamError("lead_branch_mismatch", "当前 Lead 分支与持久化小组不匹配。")
        return aggregate.team

    def add_member(
        self, identity: LeadIdentity, request: MemberCreateRequest
    ) -> TeamMemberSnapshot:
        self.authority.validate(identity, require="lead")
        member_id = f"team_member_{secrets.token_hex(8)}"
        now = utc_now()
        member = TeamMemberSnapshot(
            member_id, request.name, 1, request.role, request.writable,
            request.approval_required, request.backend_preference, None, (),
            "provisioning", None, None, None, 0, 0, now, now,
        )

        def add(aggregate: TeamAggregate) -> TeamAggregate:
            if len(aggregate.team.members) >= self.config.max_members:
                raise TeamError("member_limit", "团队成员数量达到配置上限。")
            if any(item.name == request.name for item in aggregate.team.members.values()):
                raise TeamError("member_name_conflict", "团队成员名称已存在。")
            members = dict(aggregate.team.members)
            members[member_id] = member
            return replace(aggregate, team=replace(aggregate.team, members=MappingProxyType(members)))

        aggregate = self.store.transact(identity.team_name, RevisionSet(), add)
        try:
            worktree = self.worktrees.provision(
                identity.team_name, member_id, request.name, Path(aggregate.team.workspace_root),
                aggregate.team.repository_id,
                initialization_fingerprint(self.worktrees.config.initialization),
                writable=request.writable,
            )
        except Exception:
            def rollback(current: TeamAggregate) -> TeamAggregate:
                members = dict(current.team.members)
                members.pop(member_id, None)
                return replace(current, team=replace(current.team, members=MappingProxyType(members)))
            self.store.transact(identity.team_name, RevisionSet(), rollback)
            raise

        result: TeamMemberSnapshot | None = None
        def complete(current: TeamAggregate) -> TeamAggregate:
            nonlocal result
            existing = current.team.members[member_id]
            result = replace(existing, worktree=worktree, lifecycle="offline", revision=existing.revision + 1, updated_at=utc_now())
            members = dict(current.team.members)
            members[member_id] = result
            return replace(current, team=replace(current.team, members=MappingProxyType(members)))
        self.store.transact(identity.team_name, RevisionSet(), complete)
        assert result is not None
        return result

    def upgrade_member(
        self,
        identity: LeadIdentity,
        member_id: str,
        role,
        expected_revision: int,
    ) -> TeamMemberSnapshot:
        self.authority.validate(identity, require="lead")
        updated: TeamMemberSnapshot | None = None
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal updated
            member = aggregate.team.members.get(member_id)
            if member is None:
                raise TeamError("member_not_found", "团队成员不存在。")
            if member.revision != expected_revision or member.lifecycle not in {"offline", "idle"}:
                raise TeamError("member_not_upgradeable", "成员 revision 已变化或当前状态不能升级。")
            updated = replace(member, role=role, revision=member.revision + 1, updated_at=utc_now())
            members = dict(aggregate.team.members)
            members[member_id] = updated
            return replace(aggregate, team=replace(aggregate.team, members=MappingProxyType(members)))
        self.store.transact(identity.team_name, RevisionSet(), mutation)
        assert updated is not None
        return updated

    def freeze_for_archive(self, identity: LeadIdentity) -> ArchiveReadiness:
        self.authority.validate(identity, require="lead")
        aggregate = self.store.load(identity.team_name)
        blockers: list[str] = []
        for member in aggregate.team.members.values():
            if member.lifecycle in {"starting", "running", "waiting_approval", "stopping"}:
                blockers.append(f"member:{member.name}:{member.lifecycle}")
            if member.worktree is not None:
                try:
                    state = self.worktrees.inspect(member.worktree)
                    if not state["clean"]:
                        blockers.append(f"member:{member.name}:dirty")
                    if state["unintegrated_commits"]:
                        blockers.append(f"member:{member.name}:unintegrated")
                except TeamError:
                    blockers.append(f"member:{member.name}:worktree_unknown")
        if any(item.status == "pending" for item in aggregate.approvals.values()):
            blockers.append("pending_approval")
        if any(
            item.status not in {"completed", "failed", "aborted"}
            for item in aggregate.integrations.values()
        ):
            blockers.append("active_integration")
        if any(Path(item.integration_worktree).exists() for item in aggregate.integrations.values()):
            blockers.append("integration_artifacts")
        return ArchiveReadiness(not blockers, tuple(blockers))

    def archive_team(self, identity: LeadIdentity, expected_revision: int) -> ArchiveResult:
        readiness = self.freeze_for_archive(identity)
        if not readiness.ready:
            raise TeamError("archive_blocked", f"小组暂不能归档：{', '.join(readiness.blockers)}")
        aggregate = self.store.load(identity.team_name)
        for member in aggregate.team.members.values():
            if member.worktree is not None:
                self.worktrees.dispose(member.worktree)
        archived = self.store.transact(
            identity.team_name,
            RevisionSet(team=expected_revision),
            lambda current: replace(
                current,
                team=replace(current.team, status="archived", updated_at=utc_now()),
            ),
        )
        path = self.store.archive(identity.team_name, archived.team.revision)
        self.authority.revoke_team(identity.team_name)
        return ArchiveResult(path)

    def status(self, identity: LeadIdentity) -> TeamAggregate:
        self.authority.validate(identity, require="lead")
        return self.store.load(identity.team_name)

    def start_member(self, identity: LeadIdentity, member_id: str):
        self.authority.validate(identity, require="lead")
        if self.backend is None:
            raise TeamError("backend_not_configured", "团队成员后端尚未装配。")
        aggregate = self.store.load(identity.team_name)
        member = aggregate.team.members.get(member_id)
        if member is None:
            raise TeamError("member_not_found", "团队成员不存在。")
        if member.lifecycle not in {"offline", "idle", "failed"}:
            raise TeamError("member_not_startable", "当前成员状态不能启动。")
        return self.backend.start_member(member)

    def stop_member(self, identity: LeadIdentity, member_id: str):
        self.authority.validate(identity, require="lead")
        if self.backend is None:
            raise TeamError("backend_not_configured", "团队成员后端尚未装配。")
        member = self.store.load(identity.team_name).team.members.get(member_id)
        if member is None:
            raise TeamError("member_not_found", "团队成员不存在。")
        return self.backend.stop_member(member)
