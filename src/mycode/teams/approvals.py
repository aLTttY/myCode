from __future__ import annotations

import hashlib
from dataclasses import replace
from types import MappingProxyType

from .identity import IdentityAuthority, LeadIdentity, MemberIdentity
from .mailbox import MailboxService
from .models import ApprovalRecord, RevisionSet, TeamAggregate, TeamError, utc_now
from .protocols import PlanApprovalRequestPayload, PlanDecisionPayload
from .storage import FileTeamStore


def approval_key(member_id: str, task_id: str, plan_version: int) -> str:
    return f"{member_id}:{task_id}:{plan_version}"


class ApprovalService:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        mailbox: MailboxService | None = None,
    ) -> None:
        self.store = store
        self.authority = authority
        self.mailbox = mailbox

    def submit_plan(
        self,
        identity: MemberIdentity,
        task_id: str,
        plan_body: str,
        expected_task_revision: int,
    ) -> ApprovalRecord:
        self.authority.validate(identity, require="member")
        body = plan_body.strip()
        if not body or len(body) > 100_000:
            raise TeamError("invalid_plan", "计划正文为空或过长。")
        fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
        created: ApprovalRecord | None = None

        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal created
            task = aggregate.tasks.get(task_id)
            if task is None or task.deleted_at is not None:
                raise TeamError("task_not_found", "共享任务不存在。")
            if task.assignee_id != identity.member_id:
                raise TeamError("not_assignee", "成员只能为自己的任务提交计划。")
            if task.revision != expected_task_revision:
                raise TeamError("revision_conflict", "任务 revision 已变化，请刷新后重试。")
            member = aggregate.team.members.get(identity.member_id)
            if member is None or not member.approval_required:
                raise TeamError("approval_not_required", "该成员未启用计划审批。")
            version = max(
                (approval.plan_version for approval in aggregate.approvals.values()
                 if approval.task_id == task_id and approval.member_id == identity.member_id),
                default=0,
            ) + 1
            approvals = {
                key: replace(approval, status="superseded")
                if approval.task_id == task_id and approval.member_id == identity.member_id
                and approval.status in {"pending", "approved"}
                else approval
                for key, approval in aggregate.approvals.items()
            }
            created = ApprovalRecord(
                task_id, identity.member_id, version, fingerprint, body, "pending",
                utc_now(), None, None, "", None,
            )
            approvals[approval_key(identity.member_id, task_id, version)] = created
            tasks = dict(aggregate.tasks)
            tasks[task_id] = replace(
                task, status="waiting_approval", plan_version=version,
                revision=task.revision + 1, updated_at=utc_now(),
            )
            members = dict(aggregate.team.members)
            members[identity.member_id] = replace(
                member, lifecycle="waiting_approval", revision=member.revision + 1,
                updated_at=utc_now(),
            )
            return replace(
                aggregate,
                team=replace(aggregate.team, members=MappingProxyType(members)),
                tasks=MappingProxyType(tasks), approvals=MappingProxyType(approvals),
            )

        self.store.transact(identity.team_name, RevisionSet(), mutation)
        assert created is not None
        if self.mailbox is not None:
            self.mailbox.send(identity, "lead", f"成员 {identity.member_name} 请求审批任务 {task_id} 的计划 v{created.plan_version}。", PlanApprovalRequestPayload(
                "plan_approval_request", task_id, identity.member_id,
                created.plan_version, created.plan_fingerprint,
            ), f"approval-request:{identity.member_id}:{task_id}:{created.plan_version}")
        return created

    def decide(
        self,
        identity: LeadIdentity,
        task_id: str,
        member_id: str,
        plan_version: int,
        decision: str,
        reason: str = "",
        *,
        plan_fingerprint: str | None = None,
    ) -> ApprovalRecord:
        self.authority.validate(identity, require="lead")
        if decision not in {"approved", "rejected"}:
            raise TeamError("invalid_decision", "审批决定必须是 approved 或 rejected。")
        updated: ApprovalRecord | None = None

        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal updated
            key = approval_key(member_id, task_id, plan_version)
            approval = aggregate.approvals.get(key)
            task = aggregate.tasks.get(task_id)
            member = aggregate.team.members.get(member_id)
            if approval is None or task is None or member is None:
                raise TeamError("approval_not_found", "审批记录、任务或成员不存在。")
            if approval.status != "pending" or task.assignee_id != member_id or task.plan_version != plan_version:
                raise TeamError("stale_approval", "审批请求已过期或不再匹配当前任务。")
            if plan_fingerprint is not None and approval.plan_fingerprint != plan_fingerprint:
                raise TeamError("fingerprint_mismatch", "审批计划 fingerprint 不匹配。")
            updated = replace(
                approval, status=decision, decided_at=utc_now(), decided_by=identity.actor_ref,
                reason=reason,
            )  # type: ignore[arg-type]
            approvals = dict(aggregate.approvals)
            approvals[key] = updated
            tasks = dict(aggregate.tasks)
            tasks[task_id] = replace(
                task,
                status="ready" if decision == "approved" else "blocked",
                revision=task.revision + 1,
                updated_at=utc_now(),
            )
            members = dict(aggregate.team.members)
            members[member_id] = replace(
                member,
                lifecycle="idle" if decision == "approved" else "blocked",
                revision=member.revision + 1,
                updated_at=utc_now(),
            )
            return replace(
                aggregate,
                team=replace(aggregate.team, members=MappingProxyType(members)),
                tasks=MappingProxyType(tasks), approvals=MappingProxyType(approvals),
            )

        self.store.transact(identity.team_name, RevisionSet(), mutation)
        assert updated is not None
        if self.mailbox is not None:
            aggregate = self.store.load(identity.team_name)
            recipient = aggregate.team.members[member_id].name
            delivery = self.mailbox.send(identity, recipient, f"任务 {task_id} 的计划 v{plan_version} 已{decision}。", PlanDecisionPayload(
                "plan_decision", task_id, member_id, plan_version,
                updated.plan_fingerprint, decision, reason,  # type: ignore[arg-type]
            ), f"approval-decision:{member_id}:{task_id}:{plan_version}")
            def record_message(aggregate: TeamAggregate) -> TeamAggregate:
                approvals = dict(aggregate.approvals)
                current = approvals[approval_key(member_id, task_id, plan_version)]
                approvals[approval_key(member_id, task_id, plan_version)] = replace(current, decision_message_id=delivery.message_id)
                return replace(aggregate, approvals=MappingProxyType(approvals))
            self.store.transact(identity.team_name, RevisionSet(), record_message)
            updated = replace(updated, decision_message_id=delivery.message_id)
        return updated

    def effective_approval(
        self,
        team_name: str,
        member_id: str,
        task_id: str,
        plan_version: int,
        fingerprint: str,
    ) -> ApprovalRecord | None:
        approval = self.store.load(team_name).approvals.get(approval_key(member_id, task_id, plan_version))
        if approval is None or approval.status != "approved" or approval.plan_fingerprint != fingerprint:
            return None
        return approval

    def invalidate_for_task_change(self, team_name: str, task_id: str, reason: str) -> tuple[ApprovalRecord, ...]:
        invalidated: tuple[ApprovalRecord, ...] = ()
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal invalidated
            approvals = dict(aggregate.approvals)
            changed = []
            for key, approval in tuple(approvals.items()):
                if approval.task_id == task_id and approval.status in {"pending", "approved"}:
                    approvals[key] = replace(approval, status="superseded", reason=reason)
                    changed.append(approvals[key])
            invalidated = tuple(changed)
            return replace(aggregate, approvals=MappingProxyType(approvals))
        self.store.transact(team_name, RevisionSet(), mutation)
        return invalidated

    def reconcile_notifications(self, identity: LeadIdentity) -> tuple[str, ...]:
        """Repairs the only cross-file crash window using mailbox idempotency keys."""
        self.authority.validate(identity, require="lead")
        if self.mailbox is None:
            return ()
        aggregate = self.store.load(identity.team_name)
        repaired: list[str] = []
        for approval in aggregate.approvals.values():
            member = aggregate.team.members.get(approval.member_id)
            if member is None:
                continue
            if approval.status == "pending":
                member_identity = self.authority.issue_member(
                    identity.team_name, member.member_id, member.name,
                    aggregate.team.repository_id,
                )
                try:
                    delivery = self.mailbox.send(
                        member_identity, "lead",
                        f"成员 {member.name} 请求审批任务 {approval.task_id} 的计划 v{approval.plan_version}。",
                        PlanApprovalRequestPayload(
                            "plan_approval_request", approval.task_id, approval.member_id,
                            approval.plan_version, approval.plan_fingerprint,
                        ),
                        f"approval-request:{approval.member_id}:{approval.task_id}:{approval.plan_version}",
                    )
                finally:
                    self.authority.revoke(member_identity)
                repaired.append(delivery.message_id)
            elif approval.status in {"approved", "rejected"} and approval.decision_message_id is None:
                delivery = self.mailbox.send(
                    identity, member.name,
                    f"任务 {approval.task_id} 的计划 v{approval.plan_version} 已{approval.status}。",
                    PlanDecisionPayload(
                        "plan_decision", approval.task_id, approval.member_id,
                        approval.plan_version, approval.plan_fingerprint,
                        approval.status, approval.reason,  # type: ignore[arg-type]
                    ),
                    f"approval-decision:{approval.member_id}:{approval.task_id}:{approval.plan_version}",
                )
                key = approval_key(approval.member_id, approval.task_id, approval.plan_version)
                def mutation(current: TeamAggregate) -> TeamAggregate:
                    approvals = dict(current.approvals)
                    approvals[key] = replace(approvals[key], decision_message_id=delivery.message_id)
                    return replace(current, approvals=MappingProxyType(approvals))
                self.store.transact(identity.team_name, RevisionSet(), mutation)
                repaired.append(delivery.message_id)
        return tuple(repaired)


class ApprovalToolPolicy:
    def __init__(self, approval_service: ApprovalService) -> None:
        self.approval_service = approval_service

    def may_write(
        self, team_name: str, member_id: str, task_id: str, plan_version: int, fingerprint: str
    ) -> bool:
        return self.approval_service.effective_approval(
            team_name, member_id, task_id, plan_version, fingerprint
        ) is not None
