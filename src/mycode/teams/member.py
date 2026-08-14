from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Protocol

from mycode.types import Message

from .approvals import ApprovalService
from .identity import IdentityAuthority, MemberIdentity
from .locking import FileLock
from .mailbox import MailboxService
from .models import MemberContextRecord, RevisionSet, TeamAggregate, TeamError, utc_now
from .paths import lock_path
from .protocols import TaskStatusPayload
from .storage import FileTeamStore
from .worktrees import TeamWorktreeManager


@dataclass(frozen=True)
class MemberRunRequest:
    identity: MemberIdentity
    workspace: Path
    context: tuple[Message, ...]
    inbox_messages: tuple[Message, ...]
    task_id: str | None
    task_title: str
    task_description: str
    approval_required: bool
    approval_effective: bool


@dataclass(frozen=True)
class MemberAgentResult:
    messages: tuple[Message, ...]
    summary: str = ""


@dataclass(frozen=True)
class MemberRunOutcome:
    status: str
    processed_message_ids: tuple[str, ...] = ()
    context_sequence: int = 0
    summary: str = ""


class MemberAgent(Protocol):
    def run(self, request: MemberRunRequest) -> MemberAgentResult: ...


class TeamMemberRuntime:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        mailbox: MailboxService,
        approvals: ApprovalService,
        worktrees: TeamWorktreeManager,
        agent_factory: Callable[[MemberIdentity], MemberAgent],
    ) -> None:
        self.store = store
        self.authority = authority
        self.mailbox = mailbox
        self.approvals = approvals
        self.worktrees = worktrees
        self.agent_factory = agent_factory

    def run(self, identity: MemberIdentity, cancellation: object | None = None) -> MemberRunOutcome:
        self.authority.validate(identity, require="member")
        aggregate = self.store.load(identity.team_name)
        member = aggregate.team.members.get(identity.member_id)
        if member is None or member.name != identity.member_name:
            raise TeamError("member_not_found", "团队成员身份与花名册不匹配。")
        with FileLock(
            lock_path(identity.team_name, member.name, self.store.user_root),
            timeout_seconds=self.store.config.lock_timeout_seconds,
        ):
            if member.worktree is not None:
                worktree = self.worktrees.recover(member.worktree)
                workspace = Path(worktree.worktree_path)
            else:
                workspace = Path(aggregate.team.workspace_root)
            lease = self.mailbox.reserve_unread(identity)
            task = aggregate.tasks.get(member.current_task_id) if member.current_task_id else None
            if not lease.messages and task is None:
                self._set_lifecycle(identity, "idle")
                return MemberRunOutcome("idle", context_sequence=member.context_sequence)
            self._set_lifecycle(identity, "running")
            context_records = self.store.read_context(identity.team_name, member.name)
            context = tuple(record.message for record in context_records)
            inbox = tuple(Message("user", view.message.body) for view in lease.messages)
            approval_effective = not member.approval_required
            if member.approval_required and task is not None and task.plan_version is not None:
                approval = next((
                    item for item in aggregate.approvals.values()
                    if item.member_id == member.member_id and item.task_id == task.task_id
                    and item.plan_version == task.plan_version and item.status == "approved"
                ), None)
                approval_effective = approval is not None
            request = MemberRunRequest(
                identity, workspace, context, inbox, task.task_id if task else None,
                task.title if task else "", task.description if task else "",
                member.approval_required, approval_effective,
            )
            try:
                result = self.agent_factory(identity).run(request)
                next_sequence = context_records[-1].sequence + 1 if context_records else 1
                source_ids = tuple(view.message.message_id for view in lease.messages)
                records = []
                for index, message in enumerate((*inbox, *result.messages)):
                    records.append(MemberContextRecord(
                        1, next_sequence, utc_now(), message,
                        source_ids if index < len(inbox) else (),
                    ))
                    next_sequence += 1
                if records:
                    self.store.append_context(identity.team_name, member.name, records)
                final_sequence = records[-1].sequence if records else member.context_sequence
                self.mailbox.commit_lease(identity, lease.lease_id, final_sequence)
                self._set_lifecycle(identity, "idle")
                self._notify_idle(identity, task.task_id if task else None, task.revision if task else 1)
                return MemberRunOutcome(
                    "idle", source_ids, final_sequence, result.summary,
                )
            except Exception:
                self.mailbox.release_lease(identity, lease.lease_id)
                self._set_lifecycle(identity, "failed")
                raise

    def _set_lifecycle(self, identity: MemberIdentity, lifecycle: str) -> None:
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            member = aggregate.team.members.get(identity.member_id)
            if member is None:
                raise TeamError("member_not_found", "团队成员不存在。")
            members = dict(aggregate.team.members)
            members[identity.member_id] = replace(
                member, lifecycle=lifecycle, revision=member.revision + 1, updated_at=utc_now()  # type: ignore[arg-type]
            )
            return replace(aggregate, team=replace(aggregate.team, members=MappingProxyType(members)))
        self.store.transact(identity.team_name, RevisionSet(), mutation)

    def _notify_idle(self, identity: MemberIdentity, task_id: str | None, revision: int) -> None:
        if task_id is None:
            self.mailbox.send(
                identity, "lead", f"成员 {identity.member_name} 已进入 idle。",
                idempotency_key=f"idle:{identity.member_id}:{revision}",
            )
            return
        self.mailbox.send(
            identity,
            "lead",
            f"成员 {identity.member_name} 已完成当前运行并进入 idle。",
            TaskStatusPayload("task_status", task_id, identity.member_id, "idle", revision),
            f"idle:{identity.member_id}:{task_id}:{revision}",
        )
