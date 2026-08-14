from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from mycode.types import AppConfig
from mycode.worktrees.git import GitRunner

from .approvals import ApprovalService
from .backends import CoroutineBackend, TeamBackendSelector, TmuxBackend
from .binding import TeamBinding, TeamBindingManager
from .coordinator import CoordinatorCommandPolicy
from .identity import IdentityAuthority, MemberIdentity
from .integration import IntegrationService
from .mailbox import MailboxService, WakeNotifier
from .member import MemberAgent, MemberAgentResult, MemberRunRequest, TeamMemberRuntime
from .models import AgentRoleSnapshot, RevisionSet, TeamAggregate, TeamError, TeamMemberSnapshot, utc_now
from .service import TeamActorContext, TeamService
from .storage import FileTeamStore
from .tasks import SharedTaskService
from .tools import TeamToolRegistryProvider
from .worktrees import TeamWorktreeManager
from mycode.prompts.modes import DynamicInstruction


class _IdleAgent:
    def run(self, request: MemberRunRequest) -> MemberAgentResult:
        return MemberAgentResult((), "成员运行时未配置模型执行器。")


class TeamBackendManager(WakeNotifier):
    def __init__(self, runtime: "TeamRuntime") -> None:
        self.runtime = runtime
        self._backends: dict[tuple[str, str], object] = {}
        self._guard = threading.Lock()

    def start_member(self, member: TeamMemberSnapshot):
        aggregate = self.runtime.store.load(self.runtime.bound_team_for_member(member.member_id))
        team_name = aggregate.team.name
        coroutine = CoroutineBackend(self._coroutine_runner(team_name), defer_start=True)
        tmux = TmuxBackend(
            team_name, aggregate.team.repository_id, tickets=self.runtime.tickets,
            timeout_seconds=self.runtime.config.teams.backend_start_timeout_seconds,
        )
        selection = TeamBackendSelector(tmux, coroutine).select(
            member.backend_preference,
            Path(member.worktree.worktree_path) if member.worktree is not None else Path(aggregate.team.workspace_root),
        )
        self.runtime._update_member(team_name, member.member_id,
            lifecycle="starting", actual_backend=selection.actual_backend,
            backend_diagnostics=selection.diagnostics,
        )
        current = self.runtime.store.load(team_name).team.members[member.member_id]
        with self._guard:
            previous = self._backends.get((team_name, member.member_id))
        if previous is not None and previous is not selection.backend:
            close = getattr(previous, "close", None)
            if close is not None:
                close()
        result = selection.backend.start(current)
        if selection.fallback_reason:
            result = replace(
                result,
                message=f"{result.message} {selection.fallback_reason}",
            )
        self.runtime._update_member(
            team_name, member.member_id,
            lifecycle="running" if result.started else "idle",
            actual_backend=selection.actual_backend, process=result.process,
        )
        with self._guard:
            self._backends[(team_name, member.member_id)] = selection.backend
        release = getattr(selection.backend, "release", None)
        if release is not None:
            release(self.runtime.store.load(team_name).team.members[member.member_id])
        return result

    def stop_member(self, member: TeamMemberSnapshot):
        team_name = self.runtime.bound_team_for_member(member.member_id)
        with self._guard:
            backend = self._backends.get((team_name, member.member_id))
        if backend is None:
            self.runtime._update_member(team_name, member.member_id, lifecycle="offline", process=None)
            from .backends.base import MemberStopResult
            return MemberStopResult(True, "成员后端当前未运行。")
        result = backend.stop(member, self.runtime.config.teams.shutdown_timeout_seconds)  # type: ignore[attr-defined]
        if result.stopped:
            self.runtime._update_member(team_name, member.member_id, lifecycle="offline", process=None)
        return result

    def wake(self, team_name: str, member_id: str, message_id: str) -> str:
        member = self.runtime.store.load(team_name).team.members.get(member_id)
        if member is None:
            return "成员不存在，消息已保留在邮箱。"
        with self._guard:
            backend = self._backends.get((team_name, member_id))
        if backend is None or not backend.inspect(member).running:  # type: ignore[attr-defined]
            result = self.start_member(member)
            return "" if result.started else result.message
        wake = backend.wake(member, message_id)  # type: ignore[attr-defined]
        return "" if wake.delivered else wake.message

    def close(self) -> None:
        with self._guard:
            items = tuple(self._backends.items())
            self._backends.clear()
        for (team_name, member_id), backend in items:
            member = self.runtime.store.load(team_name).team.members.get(member_id)
            if member is not None:
                result = backend.stop(member, self.runtime.config.teams.shutdown_timeout_seconds)  # type: ignore[attr-defined]
                if result.stopped:
                    self.runtime._update_member(
                        team_name, member_id,
                        lifecycle="idle" if member.current_task_id else "offline",
                        process=None,
                    )
            close = getattr(backend, "close", None)
            if close is not None:
                close()

    def _coroutine_runner(self, team_name: str):
        def run(member: TeamMemberSnapshot, cancel: threading.Event, wake: threading.Event):
            identity = self.runtime.authority.issue_member(
                team_name, member.member_id, member.name,
                self.runtime.store.load(team_name).team.repository_id,
            )
            try:
                return self.runtime.member_runtime.run(identity, cancel)
            finally:
                self.runtime.authority.revoke(identity)
        return run


class TeamRuntime:
    def __init__(
        self,
        config: AppConfig,
        workspace_root: Path,
        role_resolver: Callable[[str], AgentRoleSnapshot],
        *,
        member_agent_factory: Callable[[MemberIdentity], MemberAgent] | None = None,
        user_root: Path | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        from .identity import WorkerTicketManager

        self.config = config
        self.workspace_root = workspace_root.resolve()
        self.role_resolver = role_resolver
        self.store = FileTeamStore(user_root=user_root, config=config.teams)
        self.authority = IdentityAuthority()
        self.tickets = WorkerTicketManager(user_root=user_root)
        self.git = GitRunner(config.agents.worktree.git_timeout_seconds)
        self.worktrees = TeamWorktreeManager(config.agents.worktree, git=self.git)
        self.bindings = TeamBindingManager(
            self.store, self.authority, config.teams, environment=environment,
        )
        self.backend_manager = TeamBackendManager(self)
        self.team_service = TeamService(
            self.store, self.authority, config.teams, git=self.git,
            worktrees=self.worktrees, backend=self.backend_manager,
        )
        self.task_service = SharedTaskService(self.store, self.authority, config.teams)
        self.mailbox = MailboxService(
            self.store, self.authority, config.teams, notifier=self.backend_manager,
        )
        self.approvals = ApprovalService(self.store, self.authority, self.mailbox)
        self.integration = IntegrationService(
            self.store, self.authority, config.teams, git=self.git, worktrees=self.worktrees,
        )
        self.coordinator = CoordinatorCommandPolicy(
            config.teams, self.integration, environment=environment,
        )
        self.tools = TeamToolRegistryProvider(
            self.team_service, self.task_service, self.mailbox, self.approvals, self.integration,
            role_resolver, self.coordinator,
        )
        factory = member_agent_factory or (lambda _identity: _IdleAgent())
        self.member_runtime = TeamMemberRuntime(
            self.store, self.authority, self.mailbox, self.approvals,
            self.worktrees, factory,
        )

    def create(self, session_id: str, name: str) -> TeamBinding:
        self.team_service.create_team(name, TeamActorContext(self.workspace_root))
        return self.bindings.bind(session_id, name, self.workspace_root)

    def resume(self, session_id: str, name: str) -> TeamBinding:
        self.team_service.resume_team(name, TeamActorContext(self.workspace_root))
        self.integration.recover(name)
        self._reconcile_members_after_restart(name)
        current = self.bindings.current(session_id)
        binding = (
            self.bindings.switch(session_id, name, self.workspace_root)
            if current is not None else self.bindings.bind(session_id, name, self.workspace_root)
        )
        self.approvals.reconcile_notifications(binding.actor)
        return binding

    def switch(self, session_id: str, name: str) -> TeamBinding:
        self.team_service.resume_team(name, TeamActorContext(self.workspace_root))
        self.integration.recover(name)
        self._reconcile_members_after_restart(name)
        binding = self.bindings.switch(session_id, name, self.workspace_root)
        self.approvals.reconcile_notifications(binding.actor)
        return binding

    def status(self, session_id: str) -> TeamAggregate:
        binding = self._binding(session_id)
        return self.team_service.status(binding.actor)

    def archive(self, session_id: str):
        binding = self._binding(session_id)
        snapshot = self.store.load(binding.team_name).team
        result = self.team_service.archive_team(binding.actor, snapshot.revision)
        self.bindings.clear(session_id)
        return result

    def registry_for(self, base, session_id: str, mode: str):
        binding = self.bindings.current(session_id)
        if binding is None:
            return base
        return self.tools.for_lead(base, binding, mode)

    def reserve_lead_instructions(self, session_id: str):
        binding = self.bindings.current(session_id)
        if binding is None:
            return None
        lease = self.mailbox.reserve_unread(binding.actor)
        if not lease.messages:
            self.mailbox.release_lease(binding.actor, lease.lease_id)
            return None
        lines = ["团队邮箱有新的持久化消息；需要完整正文时使用 Mailbox get："]
        for view in lease.messages:
            message = view.message
            protocol = f" protocol={message.protocol.get('type')}" if message.protocol else ""
            lines.append(
                f"- {message.message_id} from={message.sender.name}{protocol}: {message.summary}"
            )
        instruction = DynamicInstruction(
            "mewcode_team_mailbox", "\n".join(lines), True,
        )
        return (
            (instruction,),
            lambda: self.mailbox.commit_lease(binding.actor, lease.lease_id, 0),
            lambda: self.mailbox.release_lease(binding.actor, lease.lease_id),
        )

    def clear_session(self, session_id: str) -> None:
        self.bindings.clear(session_id)

    def close(self) -> None:
        self.backend_manager.close()
        self.bindings.clear_all()

    def bound_team_for_member(self, member_id: str) -> str:
        for binding in tuple(self.bindings._bindings.values()):
            aggregate = self.store.load(binding.team_name)
            if member_id in aggregate.team.members:
                return binding.team_name
        raise TeamError("member_team_not_bound", "成员所属小组当前未绑定。")

    def _binding(self, session_id: str) -> TeamBinding:
        binding = self.bindings.current(session_id)
        if binding is None:
            raise TeamError("team_not_bound", "当前会话尚未绑定小组。")
        return binding

    def _update_member(self, team_name: str, member_id: str, **changes) -> TeamMemberSnapshot:
        updated: TeamMemberSnapshot | None = None
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal updated
            member = aggregate.team.members.get(member_id)
            if member is None:
                raise TeamError("member_not_found", "团队成员不存在。")
            updated = replace(member, revision=member.revision + 1, updated_at=utc_now(), **changes)
            members = dict(aggregate.team.members)
            members[member_id] = updated
            return replace(aggregate, team=replace(aggregate.team, members=MappingProxyType(members)))
        self.store.transact(team_name, RevisionSet(), mutation)
        assert updated is not None
        return updated

    def _reconcile_members_after_restart(self, team_name: str) -> None:
        aggregate = self.store.load(team_name)
        for member in aggregate.team.members.values():
            if member.process is None:
                continue
            if member.process.backend == "tmux":
                backend = TmuxBackend(
                    team_name, aggregate.team.repository_id, tickets=self.tickets,
                    timeout_seconds=self.config.teams.backend_start_timeout_seconds,
                )
                if backend.inspect(member).running:
                    backend.stop(member, self.config.teams.shutdown_timeout_seconds)
            lifecycle = member.lifecycle
            if lifecycle in {"starting", "running", "stopping"}:
                lifecycle = "idle" if member.current_task_id else "offline"
            self._update_member(team_name, member.member_id, lifecycle=lifecycle, process=None)
