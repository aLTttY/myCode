from __future__ import annotations

import secrets
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from mycode.types import TeamConfig
from mycode.worktrees.git import GitRunner
from mycode.worktrees.models import WorktreeError

from .identity import IdentityAuthority, LeadIdentity
from .models import (
    IntegrationRecord,
    RevisionSet,
    TeamAggregate,
    TeamError,
    VerificationResult,
    utc_now,
)
from .storage import FileTeamStore
from .worktrees import TeamWorktreeManager


@dataclass(frozen=True)
class IntegrationPlan:
    team_revision: int
    lead_branch_ref: str
    base_commit: str
    task_ids: tuple[str, ...]
    task_revisions: Mapping[str, int]
    member_commits: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class IntegrationRecoveryResult:
    integration_id: str
    status: str
    message: str


class ScopedIntegrationGitExecutor:
    OPERATIONS = {"merge_next", "abort_merge", "stage_integration", "commit_integration", "advance_lead"}

    def __init__(self, service: "IntegrationService") -> None:
        self.service = service

    def execute(self, identity: LeadIdentity, integration_id: str, operation: str) -> IntegrationRecord:
        if operation not in self.OPERATIONS:
            raise TeamError("invalid_git_operation", "Coordinator Git operation 不在固定白名单中。")
        record = self.service.get(identity, integration_id)
        if operation == "abort_merge":
            return self.service.abort(identity, integration_id)
        if operation == "advance_lead":
            return self.service.advance(identity, integration_id)
        raise TeamError(
            "operation_managed_by_state_machine",
            "该 Git operation 只能由集成状态机按冻结记录自动执行。",
        )


class IntegrationService:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        config: TeamConfig | None = None,
        *,
        git: GitRunner | None = None,
        worktrees: TeamWorktreeManager | None = None,
    ) -> None:
        self.store = store
        self.authority = authority
        self.config = config or store.config
        self.git = git or GitRunner(timeout_seconds=self.config.integration_timeout_seconds)
        self.worktrees = worktrees or TeamWorktreeManager(git=self.git)
        self.scoped_git = ScopedIntegrationGitExecutor(self)

    def preflight(
        self, identity: LeadIdentity, task_ids: Iterable[str] = ()
    ) -> IntegrationPlan:
        self.authority.validate(identity, require="lead")
        aggregate = self.store.load(identity.team_name)
        workspace = Path(aggregate.team.workspace_root)
        try:
            if self.git.current_branch_ref(workspace) != aggregate.team.lead_branch_ref:
                raise TeamError("lead_branch_mismatch", "Lead 当前分支与团队记录不一致。")
            if not self.git.is_clean(workspace):
                raise TeamError("lead_dirty", "Lead 工作区不干净，不能开始原子集成。")
            base = self.git.head(workspace)
        except WorktreeError as exc:
            raise TeamError(exc.code, exc.user_message) from exc
        requested = set(task_ids)
        selected = set(requested)
        if selected:
            pending = list(selected)
            while pending:
                current_task_id = pending.pop()
                current_task = aggregate.tasks.get(current_task_id)
                if current_task is None:
                    continue
                for dependency_id in current_task.dependency_ids:
                    dependency = aggregate.tasks[dependency_id]
                    if (
                        dependency.status == "completed"
                        and dependency.integrated_by is None
                        and dependency_id not in selected
                    ):
                        selected.add(dependency_id)
                        pending.append(dependency_id)
        candidates = [
            task for task in aggregate.tasks.values()
            if task.deleted_at is None and task.status == "completed" and task.integrated_by is None
            and (not selected or task.task_id in selected)
        ]
        if requested - {task.task_id for task in candidates}:
            raise TeamError("task_not_integratable", "请求中包含未完成、已集成或不存在的任务。")
        ordered = self._topological(candidates, aggregate)
        if not ordered:
            raise TeamError("nothing_to_integrate", "没有可集成的已完成任务。")
        member_commits: dict[str, list[str]] = {}
        task_revisions: dict[str, int] = {}
        for task in ordered:
            if task.assignee_id is None or task.result_commit is None:
                raise TeamError("task_missing_commit", f"任务 {task.task_id} 没有负责人或结果提交。")
            member = aggregate.team.members.get(task.assignee_id)
            if member is None or member.worktree is None:
                raise TeamError("member_worktree_missing", "任务负责人没有长期可写 Worktree。")
            state = self.worktrees.inspect(member.worktree)
            if not state["clean"]:
                raise TeamError("member_dirty", f"成员 {member.name} Worktree 不干净。")
            if not self.git.is_ancestor(Path(member.worktree.worktree_path), task.result_commit, member.worktree.branch_ref):
                raise TeamError("commit_identity_mismatch", "任务结果提交不属于负责人分支。")
            if not self.git.is_ancestor(Path(member.worktree.worktree_path), member.worktree.integrated_commit, task.result_commit):
                raise TeamError("commit_already_integrated", "任务结果提交不在成员待集成边界之后。")
            member_commits.setdefault(member.member_id, []).append(task.result_commit)
            task_revisions[task.task_id] = task.revision
        return IntegrationPlan(
            aggregate.team.revision, aggregate.team.lead_branch_ref, base,
            tuple(task.task_id for task in ordered), MappingProxyType(task_revisions),
            MappingProxyType({key: tuple(dict.fromkeys(value)) for key, value in member_commits.items()}),
        )

    def start(self, identity: LeadIdentity, plan: IntegrationPlan) -> IntegrationRecord:
        self.authority.validate(identity, require="lead")
        current = self.preflight(identity, plan.task_ids)
        if (
            current.base_commit != plan.base_commit
            or current.lead_branch_ref != plan.lead_branch_ref
            or dict(current.task_revisions) != dict(plan.task_revisions)
            or dict(current.member_commits) != dict(plan.member_commits)
        ):
            raise TeamError("stale_integration_plan", "集成计划已过期，请重新 preflight。")
        integration_id = f"team_int_{secrets.token_hex(8)}"
        workspace = Path(self.store.load(identity.team_name).team.workspace_root)
        branch_ref = f"refs/heads/mewcode/team/{identity.team_name}/integration/{integration_id[-16:]}"
        target = workspace / ".mycode" / "worktrees" / "teams" / identity.team_name / ".integration" / integration_id
        record = IntegrationRecord(
            integration_id, 1, "preparing", plan.lead_branch_ref, plan.base_commit,
            plan.task_ids, plan.member_commits, branch_ref, str(target), None, (), (), "", utc_now(), None,
        )
        self._put(identity.team_name, record)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.git.add_worktree(workspace, target, branch_ref, plan.base_commit)
            self.worktrees.initialize_path(workspace, target)
            record = self._change(identity.team_name, integration_id, status="merging")
            aggregate = self.store.load(identity.team_name)
            ordered_commits = tuple(
                (task_id, aggregate.tasks[task_id].result_commit)
                for task_id in plan.task_ids
            )
            merge_commits = tuple(
                (task_id, commit)
                for task_id, commit in ordered_commits
                if commit is not None and not any(
                    other is not None and other != commit
                    and self.git.is_ancestor(target, commit, other)
                    for _other_task_id, other in ordered_commits
                )
            )
            for task_id, commit in merge_commits:
                assert commit is not None
                result = self.git.merge_no_ff(target, commit, f"Integrate team task {task_id}")
                if result.returncode != 0:
                    conflicts = self.git.conflict_paths(target)
                    self.git.abort_merge(target)
                    return self._change(
                        identity.team_name, integration_id, status="conflicted",
                        conflict_paths=conflicts,
                        failure_reason="成员提交存在无法自动解决的冲突。",
                        finished_at=utc_now(),
                    )
            record = self._change(identity.team_name, integration_id, status="validating")
            verification_results = self._verify(target)
            if any(result.returncode != 0 for result in verification_results):
                return self._change(
                    identity.team_name, integration_id, status="failed",
                    verification_results=verification_results,
                    failure_reason="集成验证命令失败。", finished_at=utc_now(),
                )
            merged_commit = self.git.head(target)
            record = self._change(
                identity.team_name, integration_id, status="ready_to_advance",
                merged_commit=merged_commit, verification_results=verification_results,
            )
            return self.advance(identity, integration_id)
        except (TeamError, WorktreeError, OSError, subprocess.SubprocessError) as exc:
            return self._change(
                identity.team_name, integration_id, status="failed",
                failure_reason=getattr(exc, "user_message", f"集成执行失败：{type(exc).__name__}"),
                finished_at=utc_now(),
            )

    def advance(self, identity: LeadIdentity, integration_id: str) -> IntegrationRecord:
        self.authority.validate(identity, require="lead")
        record = self.get(identity, integration_id)
        if record.status not in {"ready_to_advance", "advancing"} or record.merged_commit is None:
            raise TeamError("integration_not_ready", "集成尚未完成验证，不能推进 Lead。")
        aggregate = self.store.load(identity.team_name)
        workspace = Path(aggregate.team.workspace_root)
        if self.git.head(workspace) != record.base_commit or not self.git.is_clean(workspace):
            raise TeamError("lead_changed", "Lead HEAD 或工作区已变化，原子推进已拒绝。")
        self._change(identity.team_name, integration_id, status="advancing")
        try:
            self.git.fast_forward(workspace, record.integration_branch_ref)
        except WorktreeError as exc:
            return self._change(
                identity.team_name, integration_id, status="failed",
                failure_reason=exc.user_message, finished_at=utc_now(),
            )
        if self.git.head(workspace) != record.merged_commit:
            raise TeamError("advance_verification_failed", "Lead 推进结果与已验证提交不一致。")
        completed = self._finalize_completed(identity.team_name, integration_id)
        warning = self._cleanup_worktree(workspace, record)
        if warning:
            completed = self._change(
                identity.team_name, integration_id,
                failure_reason=warning,
            )
        return completed

    def _finalize_completed(self, team_name: str, integration_id: str) -> IntegrationRecord:
        completed: IntegrationRecord | None = None
        def mutation(current: TeamAggregate) -> TeamAggregate:
            nonlocal completed
            integrations = dict(current.integrations)
            active = integrations[integration_id]
            if active.status == "completed":
                completed = active
                return current
            completed = replace(active, status="completed", revision=active.revision + 1, finished_at=utc_now())
            integrations[integration_id] = completed
            tasks = dict(current.tasks)
            members = dict(current.team.members)
            for task_id in active.task_ids:
                task = tasks[task_id]
                tasks[task_id] = replace(task, integrated_by=integration_id, revision=task.revision + 1, updated_at=utc_now())
                if task.assignee_id is not None:
                    member = members[task.assignee_id]
                    if member.worktree is not None:
                        worktree = replace(member.worktree, integrated_commit=task.result_commit or member.worktree.integrated_commit, last_active_at=utc_now())
                        members[member.member_id] = replace(member, worktree=worktree, revision=member.revision + 1, updated_at=utc_now())
            return replace(
                current,
                team=replace(current.team, members=MappingProxyType(members)),
                tasks=MappingProxyType(tasks), integrations=MappingProxyType(integrations),
            )
        self.store.transact(team_name, RevisionSet(), mutation)
        assert completed is not None
        return completed

    def get(self, identity: LeadIdentity, integration_id: str) -> IntegrationRecord:
        self.authority.validate(identity, require="lead")
        record = self.store.load(identity.team_name).integrations.get(integration_id)
        if record is None:
            raise TeamError("integration_not_found", "集成事务不存在。")
        return record

    def abort(self, identity: LeadIdentity, integration_id: str) -> IntegrationRecord:
        self.authority.validate(identity, require="lead")
        record = self.get(identity, integration_id)
        if record.status == "aborted":
            return record
        if record.status == "completed":
            workspace = Path(self.store.load(identity.team_name).team.workspace_root)
            warning = self._cleanup_worktree(workspace, record)
            return self._change(
                identity.team_name, integration_id,
                failure_reason=warning,
            ) if warning != record.failure_reason else record
        target = Path(record.integration_worktree)
        if target.exists():
            self.git.abort_merge(target)
        result = self._change(identity.team_name, integration_id, status="aborted", finished_at=utc_now())
        workspace = Path(self.store.load(identity.team_name).team.workspace_root)
        warning = self._cleanup_worktree(workspace, result)
        if warning:
            result = self._change(identity.team_name, integration_id, failure_reason=warning)
        return result

    def recover(self, team_name: str) -> tuple[IntegrationRecoveryResult, ...]:
        aggregate = self.store.load(team_name)
        workspace = Path(aggregate.team.workspace_root)
        head = self.git.head(workspace)
        results = []
        for record in aggregate.integrations.values():
            if record.status == "advancing" and record.merged_commit == head:
                self._finalize_completed(team_name, record.integration_id)
                warning = self._cleanup_worktree(workspace, record)
                if warning:
                    self._change(team_name, record.integration_id, failure_reason=warning)
                results.append(IntegrationRecoveryResult(record.integration_id, "completed", "已根据 Lead ref 补记完成状态。"))
            elif record.status == "advancing" and record.base_commit == head:
                self._change(team_name, record.integration_id, status="ready_to_advance")
                results.append(IntegrationRecoveryResult(record.integration_id, "recoverable", "Lead 尚未推进，已恢复到 ready_to_advance。"))
            elif record.status == "advancing":
                self._change(
                    team_name, record.integration_id, status="failed",
                    failure_reason="Lead ref 既不是冻结基线也不是已验证合并提交。",
                    finished_at=utc_now(),
                )
                results.append(IntegrationRecoveryResult(record.integration_id, "needs_attention", "Lead ref 已分叉，拒绝自动恢复。"))
            elif record.status in {"preparing", "merging", "validating"}:
                target = Path(record.integration_worktree)
                if target.exists():
                    self.git.abort_merge(target)
                failed = self._change(
                    team_name, record.integration_id, status="failed",
                    failure_reason="进程在集成完成验证前中断，已安全回滚临时集成。",
                    finished_at=utc_now(),
                )
                warning = self._cleanup_worktree(workspace, failed)
                if warning:
                    self._change(team_name, record.integration_id, failure_reason=warning)
                results.append(IntegrationRecoveryResult(record.integration_id, "rolled_back", "已回滚中断的临时集成，Lead 未改变。"))
            elif record.status == "ready_to_advance":
                results.append(IntegrationRecoveryResult(record.integration_id, "recoverable", "持久化集成可继续或显式中止。"))
        return tuple(results)

    def _verify(self, target: Path) -> tuple[VerificationResult, ...]:
        results = []
        started = utc_now()
        diff = self.git.diff_check(target)
        results.append(VerificationResult(
            "builtin-git-diff-check", diff.returncode,
            diff.stderr.decode("utf-8", errors="replace")[-1000:], started, utc_now(),
        ))
        if diff.returncode != 0:
            return tuple(results)
        for command in self.config.verification_commands:
            started = utc_now()
            try:
                completed = subprocess.run(
                    command.argv, cwd=target, shell=False, capture_output=True,
                    timeout=command.timeout_seconds, check=False,
                    env={"PATH": str(Path("/usr/bin")) + ":/bin:/usr/local/bin", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"},
                )
                summary = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")[-2000:]
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                summary, returncode = "验证命令超时。", 124
            results.append(VerificationResult(command.command_id, returncode, summary, started, utc_now()))
            if returncode != 0:
                break
        return tuple(results)

    def _put(self, team_name: str, record: IntegrationRecord) -> IntegrationRecord:
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            integrations = dict(aggregate.integrations)
            if record.integration_id in integrations:
                raise TeamError("integration_exists", "集成事务已存在。")
            integrations[record.integration_id] = record
            return replace(aggregate, integrations=MappingProxyType(integrations))
        self.store.transact(team_name, RevisionSet(), mutation)
        return record

    def _change(self, team_name: str, integration_id: str, **changes) -> IntegrationRecord:
        updated: IntegrationRecord | None = None
        def mutation(aggregate: TeamAggregate) -> TeamAggregate:
            nonlocal updated
            current = aggregate.integrations.get(integration_id)
            if current is None:
                raise TeamError("integration_not_found", "集成事务不存在。")
            updated = replace(current, revision=current.revision + 1, **changes)
            integrations = dict(aggregate.integrations)
            integrations[integration_id] = updated
            return replace(aggregate, integrations=MappingProxyType(integrations))
        self.store.transact(team_name, RevisionSet(), mutation)
        assert updated is not None
        return updated

    def _cleanup_worktree(self, workspace: Path, record: IntegrationRecord) -> str:
        target = Path(record.integration_worktree)
        try:
            if target.exists():
                self.git.unlock_worktree(workspace, target)
                self.git.remove_worktree(workspace, target)
            if self.git.ref_exists(workspace, record.integration_branch_ref):
                self.git.delete_ref(workspace, record.integration_branch_ref, self.git.ref_tip(workspace, record.integration_branch_ref))
        except WorktreeError as exc:
            return f"集成结果已确定，但临时 Worktree 清理失败：{exc.user_message}"
        return ""

    @staticmethod
    def _topological(tasks, aggregate: TeamAggregate):
        selected = {task.task_id: task for task in tasks}
        result, visiting, visited = [], set(), set()
        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise TeamError("dependency_cycle", "共享任务依赖形成循环。")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in sorted(aggregate.tasks[task_id].dependency_ids):
                if dependency in selected:
                    visit(dependency)
                elif aggregate.tasks[dependency].status != "completed":
                    raise TeamError("dependency_incomplete", "待集成任务仍有未完成依赖。")
            visiting.remove(task_id)
            visited.add(task_id)
            result.append(selected[task_id])
        for task_id in sorted(selected):
            visit(task_id)
        return tuple(result)
