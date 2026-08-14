from __future__ import annotations

import secrets
from dataclasses import replace
from types import MappingProxyType
from typing import Iterable, Mapping

from mycode.types import TeamConfig

from .identity import ActorIdentity, IdentityAuthority, LeadIdentity, MemberIdentity
from .models import (
    RevisionSet,
    SharedTaskRecord,
    TaskCreateRequest,
    TaskWorkEntry,
    TeamAggregate,
    TeamError,
    utc_now,
)
from .paths import validate_task_id
from .storage import FileTeamStore


class SharedTaskService:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        config: TeamConfig | None = None,
    ) -> None:
        self.store = store
        self.authority = authority
        self.config = config or store.config

    def list_tasks(
        self,
        identity: ActorIdentity,
        query: Mapping[str, object] | None = None,
    ) -> tuple[SharedTaskRecord, ...]:
        self.authority.validate(identity)
        include_deleted = bool((query or {}).get("include_deleted", False))
        status = (query or {}).get("status")
        tasks = self.store.load(identity.team_name).tasks.values()
        return tuple(
            sorted(
                (
                    task for task in tasks
                    if (include_deleted or task.deleted_at is None)
                    and (status is None or task.status == status)
                ),
                key=lambda task: (task.created_at, task.task_id),
            )
        )

    def get_task(
        self, identity: ActorIdentity, task_id: str, include_deleted: bool = False
    ) -> SharedTaskRecord:
        self.authority.validate(identity)
        task = self.store.load(identity.team_name).tasks.get(validate_task_id(task_id))
        if task is None or (task.deleted_at is not None and not include_deleted):
            raise TeamError("task_not_found", "共享任务不存在。")
        return task

    def create_task(
        self, identity: ActorIdentity, request: TaskCreateRequest
    ) -> SharedTaskRecord:
        self.authority.validate(identity)
        title = request.title.strip()
        if not title or len(title) > 500 or len(request.description) > 20_000:
            raise TeamError("invalid_task", "任务标题或描述长度非法。")
        if isinstance(identity, MemberIdentity) and request.assignee_id is not None:
            raise TeamError("lead_required", "成员创建任务时不能指派负责人。")
        if len(request.dependency_ids) > self.config.max_dependencies_per_task:
            raise TeamError("dependency_limit", "任务依赖数量达到配置上限。")
        task_id = f"team_task_{secrets.token_hex(8)}"
        now = utc_now()
        created: SharedTaskRecord | None = None

        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal created
            if len(aggregate.tasks) >= self.config.max_tasks:
                raise TeamError("task_limit", "共享任务数量达到配置上限。")
            self._validate_dependencies(aggregate.tasks, task_id, request.dependency_ids)
            if request.assignee_id is not None and request.assignee_id not in aggregate.team.members:
                raise TeamError("member_not_found", "任务负责人不在当前小组。")
            status = self._derived_status(aggregate.tasks, request.dependency_ids, request.assignee_id)
            created = SharedTaskRecord(
                task_id, 1, title, request.description, status, request.assignee_id,
                tuple(dict.fromkeys(request.dependency_ids)), identity.actor_ref, (), None,
                None, None, None, now, now,
            )
            tasks = dict(aggregate.tasks)
            tasks[task_id] = created
            return replace(aggregate, tasks=MappingProxyType(tasks))

        self.store.transact(identity.team_name, RevisionSet(), mutation)
        assert created is not None
        return created

    def update(
        self,
        identity: LeadIdentity,
        task_id: str,
        *,
        expected_revision: int,
        title: str | None = None,
        description: str | None = None,
    ) -> SharedTaskRecord:
        self.authority.validate(identity, require="lead")
        return self._replace_task(
            identity, task_id, expected_revision,
            lambda task, _aggregate: replace(
                task,
                title=task.title if title is None else self._valid_title(title),
                description=task.description if description is None else description,
                plan_version=None if description is not None else task.plan_version,
            ),
        )

    def update_own(
        self,
        identity: MemberIdentity,
        task_id: str,
        *,
        expected_revision: int,
        status: str | None = None,
        work_log: str | None = None,
    ) -> SharedTaskRecord:
        self.authority.validate(identity, require="member")

        def transform(task: SharedTaskRecord, aggregate: TeamAggregate) -> SharedTaskRecord:
            if task.assignee_id != identity.member_id:
                raise TeamError("not_assignee", "成员只能更新分配给自己的任务。")
            allowed = {
                "ready": {"running", "blocked"},
                "running": {"blocked", "completed"},
                "blocked": {"running", "completed"},
            }
            next_status = task.status if status is None else status
            if status is not None and status not in allowed.get(task.status, set()):
                raise TeamError("invalid_task_transition", "共享任务状态转换非法。")
            if next_status == "running":
                blockers = self._incomplete_dependencies(task, aggregate.tasks)
                if blockers:
                    raise TeamError("dependency_blocked", f"任务仍被依赖阻塞：{', '.join(blockers)}")
                member = aggregate.team.members.get(identity.member_id)
                if member is not None and member.approval_required:
                    effective = any(
                        approval.member_id == identity.member_id
                        and approval.task_id == task.task_id
                        and approval.plan_version == task.plan_version
                        and approval.status == "approved"
                        for approval in aggregate.approvals.values()
                    )
                    if not effective:
                        raise TeamError("approval_required", "当前任务计划尚未获得匹配版本的 Lead 批准。")
            logs = task.work_log
            if work_log is not None:
                if not work_log.strip() or len(work_log) > 2_000:
                    raise TeamError("invalid_work_log", "工作日志为空或过长。")
                if len(logs) >= self.config.max_work_log_entries:
                    raise TeamError("work_log_limit", "任务工作日志达到配置上限。")
                logs += (TaskWorkEntry(utc_now(), identity.actor_ref, work_log.strip()),)
            return replace(task, status=next_status, work_log=logs)  # type: ignore[arg-type]

        return self._replace_task(identity, task_id, expected_revision, transform)

    def assign(
        self,
        identity: LeadIdentity,
        task_id: str,
        member_id: str,
        expected_revision: int,
    ) -> SharedTaskRecord:
        self.authority.validate(identity, require="lead")

        def transform(task: SharedTaskRecord, aggregate: TeamAggregate) -> SharedTaskRecord:
            if member_id not in aggregate.team.members:
                raise TeamError("member_not_found", "任务负责人不在当前小组。")
            if task.status in {"running", "completed", "cancelled"}:
                raise TeamError("task_not_assignable", "当前任务状态不能重新指派。")
            return replace(
                task,
                assignee_id=member_id,
                status=self._derived_status(aggregate.tasks, task.dependency_ids, member_id),
                plan_version=None,
            )

        return self._replace_task(identity, task_id, expected_revision, transform)

    def set_dependencies(
        self,
        identity: LeadIdentity,
        task_id: str,
        dependency_ids: Iterable[str],
        expected_revision: int,
    ) -> SharedTaskRecord:
        self.authority.validate(identity, require="lead")
        dependencies = tuple(dict.fromkeys(dependency_ids))
        if len(dependencies) > self.config.max_dependencies_per_task:
            raise TeamError("dependency_limit", "任务依赖数量达到配置上限。")

        def transform(task: SharedTaskRecord, aggregate: TeamAggregate) -> SharedTaskRecord:
            if task.status in {"running", "completed", "cancelled"}:
                raise TeamError("task_dependencies_locked", "当前任务状态不能修改依赖。")
            self._validate_dependencies(aggregate.tasks, task.task_id, dependencies)
            candidate = dict(aggregate.tasks)
            candidate[task.task_id] = replace(task, dependency_ids=dependencies)
            self._assert_acyclic(candidate)
            return replace(
                task,
                dependency_ids=dependencies,
                status=self._derived_status(candidate, dependencies, task.assignee_id),
                plan_version=None,
            )

        return self._replace_task(identity, task_id, expected_revision, transform)

    def request_start(
        self, identity: MemberIdentity, task_id: str, expected_revision: int
    ) -> SharedTaskRecord:
        task = self.update_own(identity, task_id, expected_revision=expected_revision, status="running")
        self._set_member_task(identity, task.task_id, "running")
        return task

    def complete(
        self,
        identity: MemberIdentity,
        task_id: str,
        result_summary: str,
        expected_revision: int,
        *,
        result_commit: str | None = None,
    ) -> SharedTaskRecord:
        task = self.update_own(
            identity,
            task_id,
            expected_revision=expected_revision,
            status="completed",
            work_log=result_summary,
        )
        if result_commit is None:
            self._set_member_task(identity, None, "idle")
            self._recompute_dependents(identity.team_name)
            return task
        updated = self._replace_task(
            identity,
            task_id,
            task.revision,
            lambda current, _aggregate: replace(current, result_commit=result_commit),
        )
        self._recompute_dependents(identity.team_name)
        self._set_member_task(identity, None, "idle")
        return updated

    def _set_member_task(
        self, identity: MemberIdentity, task_id: str | None, lifecycle: str
    ) -> None:
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            member = aggregate.team.members.get(identity.member_id)
            if member is None:
                raise TeamError("member_not_found", "团队成员不存在。")
            members = dict(aggregate.team.members)
            members[identity.member_id] = replace(
                member, current_task_id=task_id, lifecycle=lifecycle,
                revision=member.revision + 1, updated_at=utc_now(),
            )
            return replace(
                aggregate,
                team=replace(aggregate.team, members=MappingProxyType(members)),
            )
        self.store.transact(identity.team_name, RevisionSet(), mutation)

    def cancel(
        self, identity: LeadIdentity, task_id: str, expected_revision: int
    ) -> SharedTaskRecord:
        self.authority.validate(identity, require="lead")
        return self._replace_task(
            identity, task_id, expected_revision,
            lambda task, _aggregate: replace(task, status="cancelled"),
        )

    def delete(
        self, identity: LeadIdentity, task_id: str, expected_revision: int
    ) -> SharedTaskRecord:
        self.authority.validate(identity, require="lead")

        def transform(task: SharedTaskRecord, aggregate: TeamAggregate) -> SharedTaskRecord:
            if task.status == "running":
                raise TeamError("task_running", "运行中的任务不能删除。")
            dependents = [
                item.task_id for item in aggregate.tasks.values()
                if item.deleted_at is None and task.task_id in item.dependency_ids
                and item.status not in {"completed", "cancelled"}
            ]
            if dependents:
                raise TeamError("task_referenced", f"任务仍被活动任务依赖：{', '.join(sorted(dependents))}")
            pending = any(
                approval.task_id == task.task_id and approval.status == "pending"
                for approval in aggregate.approvals.values()
            )
            if pending:
                raise TeamError("approval_pending", "任务仍有待审批计划，不能删除。")
            return replace(task, deleted_at=utc_now())

        return self._replace_task(identity, task_id, expected_revision, transform)

    def start_ready(
        self, identity: LeadIdentity, task_ids: Iterable[str] = ()
    ) -> tuple[SharedTaskRecord, ...]:
        self.authority.validate(identity, require="lead")
        wanted = set(task_ids)
        tasks = self.list_tasks(identity)
        return tuple(
            task for task in self._topological(tasks)
            if task.status == "ready" and (not wanted or task.task_id in wanted)
        )

    def _replace_task(self, identity: ActorIdentity, task_id: str, expected_revision: int, transform):
        validate_task_id(task_id)
        updated: SharedTaskRecord | None = None

        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal updated
            task = aggregate.tasks.get(task_id)
            if task is None or task.deleted_at is not None:
                raise TeamError("task_not_found", "共享任务不存在。")
            if task.revision != expected_revision:
                raise TeamError("revision_conflict", "任务 revision 已变化，请刷新后重试。")
            candidate = transform(task, aggregate)
            updated = replace(candidate, revision=task.revision + 1, updated_at=utc_now())
            tasks = dict(aggregate.tasks)
            tasks[task_id] = updated
            return replace(aggregate, tasks=MappingProxyType(tasks))

        self.store.transact(identity.team_name, RevisionSet(), mutation)
        assert updated is not None
        return updated

    def _recompute_dependents(self, team_name: str) -> None:
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            tasks = dict(aggregate.tasks)
            changed = False
            for task_id, task in tuple(tasks.items()):
                if task.deleted_at is not None or task.status not in {"dependency_blocked", "ready", "pending"}:
                    continue
                status = self._derived_status(tasks, task.dependency_ids, task.assignee_id)
                if status != task.status:
                    tasks[task_id] = replace(task, status=status, revision=task.revision + 1, updated_at=utc_now())
                    changed = True
            return replace(aggregate, tasks=MappingProxyType(tasks)) if changed else aggregate
        self.store.transact(team_name, RevisionSet(), mutation)

    @staticmethod
    def _valid_title(title: str) -> str:
        value = title.strip()
        if not value or len(value) > 500:
            raise TeamError("invalid_task", "任务标题为空或过长。")
        return value

    @staticmethod
    def _incomplete_dependencies(task: SharedTaskRecord, tasks: Mapping[str, SharedTaskRecord]) -> tuple[str, ...]:
        return tuple(dependency for dependency in task.dependency_ids if tasks[dependency].status != "completed")

    def _derived_status(
        self,
        tasks: Mapping[str, SharedTaskRecord],
        dependencies: Iterable[str],
        assignee_id: str | None,
    ) -> str:
        dependencies = tuple(dependencies)
        if any(tasks[dependency].status != "completed" for dependency in dependencies):
            return "dependency_blocked"
        return "ready" if assignee_id is not None else "pending"

    @staticmethod
    def _validate_dependencies(tasks: Mapping[str, SharedTaskRecord], task_id: str, dependencies: Iterable[str]) -> None:
        for dependency in dependencies:
            validate_task_id(dependency)
            if dependency == task_id:
                raise TeamError("self_dependency", "任务不能依赖自身。")
            if dependency not in tasks or tasks[dependency].deleted_at is not None:
                raise TeamError("missing_dependency", "任务依赖不存在或已删除。")

    @staticmethod
    def _assert_acyclic(tasks: Mapping[str, SharedTaskRecord]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise TeamError("dependency_cycle", "任务依赖形成循环。")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in tasks[task_id].dependency_ids:
                if dependency in tasks and tasks[dependency].deleted_at is None:
                    visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)
        for task_id, task in tasks.items():
            if task.deleted_at is None:
                visit(task_id)

    @classmethod
    def _topological(cls, tasks: Iterable[SharedTaskRecord]) -> tuple[SharedTaskRecord, ...]:
        mapping = {task.task_id: task for task in tasks}
        cls._assert_acyclic(mapping)
        visited: set[str] = set()
        result: list[SharedTaskRecord] = []
        def visit(task_id: str) -> None:
            if task_id in visited:
                return
            for dependency in sorted(mapping[task_id].dependency_ids):
                if dependency in mapping:
                    visit(dependency)
            visited.add(task_id)
            result.append(mapping[task_id])
        for task_id in sorted(mapping):
            visit(task_id)
        return tuple(result)
