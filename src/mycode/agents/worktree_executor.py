from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable

from mycode.worktrees.context import WorkspaceContextFactory
from mycode.worktrees.initializer import WorkspaceInitializer
from mycode.worktrees.manager import WorktreeManager
from mycode.worktrees.models import WorktreeDisposition, WorktreeTaskSummary

from .models import ChildRunSpec, TaskOutcome
from .runner import ChildAgentExecutor


class WorktreeTaskExecutor:
    def __init__(
        self,
        child_executor: ChildAgentExecutor,
        manager: WorktreeManager,
        initializer: WorkspaceInitializer,
        contexts: WorkspaceContextFactory,
        state_sink: Callable[[str, WorktreeTaskSummary], None] | None = None,
    ) -> None:
        self.child_executor = child_executor
        self.manager = manager
        self.initializer = initializer
        self.contexts = contexts
        self.state_sink = state_sink

    def set_state_sink(
        self,
        sink: Callable[[str, WorktreeTaskSummary], None],
    ) -> None:
        self.state_sink = sink

    def run(self, spec: ChildRunSpec, cancellation: object) -> TaskOutcome:
        if spec.worktree_request is None:
            return self.child_executor.run(spec, cancellation)
        lease = None
        activated = False
        outcome: TaskOutcome | None = None
        try:
            lease = self.manager.enter(spec.worktree_request)
            initialized = self.initializer.initialize(lease)
            lease = self.manager.activate(lease, initialized)
            activated = True
            self._publish(
                spec.task_id,
                WorktreeTaskSummary(
                    path=str(lease.identity.worktree_path),
                    branch=lease.identity.branch_ref,
                    base_commit=lease.identity.base_commit,
                    status="active",
                    last_active_at=lease.identity.last_active_at,
                ),
            )
            workspace = self.contexts.build(lease, initialized)
            outcome = self.child_executor.run(spec, cancellation, workspace)
        except Exception as exc:
            request = spec.worktree_request
            outcome = TaskOutcome(
                "cancelled" if cancellation.is_cancelled() else "failed",
                failure_reason=(
                    "任务已取消。"
                    if cancellation.is_cancelled()
                    else f"Worktree 子 Agent 执行失败（{type(exc).__name__}）。"
                ),
                worktree=(
                    WorktreeTaskSummary(
                        path=str(request.worktree_path),
                        branch=request.branch_ref,
                        base_commit=request.base_commit,
                        status="cleanup_failed",
                        retention_reason=(
                            "Worktree 生命周期失败，无法证明目标已安全清理。"
                        ),
                    )
                    if request is not None
                    else None
                ),
            )
        finally:
            disposition = None
            if lease is not None:
                disposition = (
                    self.manager.exit(lease)
                    if activated
                    else self.manager.abort_initialization(lease)
                )
            if outcome is not None and disposition is not None:
                outcome = replace(outcome, worktree=_summary(disposition))
        assert outcome is not None
        return outcome

    def _publish(self, task_id: str, summary: WorktreeTaskSummary) -> None:
        if self.state_sink is None:
            return
        try:
            self.state_sink(task_id, summary)
        except Exception:
            pass


def _summary(disposition: WorktreeDisposition) -> WorktreeTaskSummary:
    identity = disposition.identity
    return WorktreeTaskSummary(
        path=str(identity.worktree_path),
        branch=identity.branch_ref,
        base_commit=identity.base_commit,
        status=disposition.status,
        retention_reason=disposition.reason,
        last_active_at=identity.last_active_at,
    )
