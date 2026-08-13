from __future__ import annotations

from pathlib import Path

from mycode.agents.models import AgentDefinition, ChildRunSpec, TaskOutcome
from mycode.agents.worktree_executor import WorktreeTaskExecutor
from mycode.types import ToolContext, WorktreeConfig, WorktreeInitRule
from mycode.worktrees import (
    WorkspaceContextFactory,
    WorkspaceInitializer,
    WorktreeManager,
    initialization_fingerprint,
)

from worktree_testkit import git, init_repo


TASK_ID = "agt_3333333333333333"


class Cancellation:
    def is_cancelled(self) -> bool:
        return False


class Cancelled:
    def is_cancelled(self) -> bool:
        return True


def role() -> AgentDefinition:
    return AgentDefinition(
        "builder",
        "build",
        ("read_file", "write_file"),
        (),
        "inherit",
        4,
        "strict",
        "prompt",
        "project",
        "builder.md",
        "fingerprint",
        "worktree",
    )


def test_executor_binds_context_and_retains_child_change(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "MYCODE.md").write_text("main instruction\n", encoding="utf-8")
    git(repo, "add", "MYCODE.md")
    git(repo, "commit", "-m", "instructions")
    config = WorktreeConfig(initialization=())
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "builder",
        repo,
        initialization_fingerprint(()),
    )
    observed = {}

    class Child:
        def run(self, spec, cancellation, workspace_context=None):
            assert workspace_context is not None
            observed["cwd"] = workspace_context.tool_context.workspace_root
            observed["instruction"] = workspace_context.instruction_bundle.content
            observed["isolation"] = workspace_context.isolation_instruction.content
            (workspace_context.tool_context.workspace_root / "tracked.txt").write_text(
                "child\n", encoding="utf-8"
            )
            return TaskOutcome("completed", result="done")

    states = []
    executor = WorktreeTaskExecutor(
        Child(),  # type: ignore[arg-type]
        manager,
        WorkspaceInitializer(manager.git, config),
        WorkspaceContextFactory(
            ToolContext(repo, excluded_roots=(repo / ".mycode" / "worktrees",))
        ),
        state_sink=lambda task_id, summary: states.append((task_id, summary)),
    )
    spec = ChildRunSpec(
        TASK_ID,
        "session",
        "defined",
        "work",
        role(),
        "model",
        False,
        "default",
        None,
        object(),
        request,
    )
    original_cwd = Path.cwd()

    outcome = executor.run(spec, Cancellation())

    assert Path.cwd() == original_cwd
    assert outcome.status == "completed"
    assert outcome.worktree is not None
    assert outcome.worktree.status == "retained_changes"
    assert [(task_id, summary.status) for task_id, summary in states] == [
        (TASK_ID, "active")
    ]
    assert observed["cwd"] != repo
    assert "main instruction" in observed["instruction"]
    assert str(repo) in observed["isolation"]
    assert (Path(outcome.worktree.path) / "tracked.txt").read_text(encoding="utf-8") == "child\n"


def test_shared_spec_uses_existing_executor_path(tmp_path: Path) -> None:
    called = []

    class Child:
        def run(self, spec, cancellation):
            called.append(spec.task_id)
            return TaskOutcome("completed", result="shared")

    repo = init_repo(tmp_path / "repo")
    manager = WorktreeManager(WorktreeConfig(initialization=()))
    executor = WorktreeTaskExecutor(
        Child(),  # type: ignore[arg-type]
        manager,
        WorkspaceInitializer(manager.git, manager.config),
        WorkspaceContextFactory(ToolContext(repo)),
    )
    spec = ChildRunSpec(
        "shared",
        "session",
        "fork",
        "work",
        None,
        "model",
        True,
        "default",
        None,
    )

    outcome = executor.run(spec, Cancellation())

    assert outcome.result == "shared"
    assert called == ["shared"]


def _isolated_spec(repo: Path, manager: WorktreeManager, task_id: str) -> ChildRunSpec:
    request = manager.requests.prepare(
        task_id,
        "builder",
        repo,
        initialization_fingerprint(manager.config.initialization),
    )
    return ChildRunSpec(
        task_id,
        "session",
        "defined",
        "work",
        role(),
        "model",
        False,
        "default",
        None,
        object(),
        request,
    )


def test_failure_and_cancel_both_finish_worktree_protection(tmp_path: Path) -> None:
    failed_repo = init_repo(tmp_path / "failed-repo")
    cancelled_repo = init_repo(tmp_path / "cancelled-repo")
    failed_manager = WorktreeManager(WorktreeConfig(initialization=()))
    cancelled_manager = WorktreeManager(WorktreeConfig(initialization=()))

    class FailingChild:
        def run(self, spec, cancellation, workspace_context=None):
            assert workspace_context is not None
            (workspace_context.workspace_key / "tracked.txt").write_text(
                "valuable failure output\n",
                encoding="utf-8",
            )
            raise RuntimeError("SUPER_SECRET_EXCEPTION_TEXT")

    class CancelledChild:
        def run(self, spec, cancellation, workspace_context=None):
            assert workspace_context is not None
            assert cancellation.is_cancelled()
            return TaskOutcome("cancelled", failure_reason="cancelled")

    failed_executor = WorktreeTaskExecutor(
        FailingChild(),  # type: ignore[arg-type]
        failed_manager,
        WorkspaceInitializer(failed_manager.git, failed_manager.config),
        WorkspaceContextFactory(ToolContext(failed_repo)),
    )
    cancelled_executor = WorktreeTaskExecutor(
        CancelledChild(),  # type: ignore[arg-type]
        cancelled_manager,
        WorkspaceInitializer(cancelled_manager.git, cancelled_manager.config),
        WorkspaceContextFactory(ToolContext(cancelled_repo)),
    )

    failed = failed_executor.run(
        _isolated_spec(failed_repo, failed_manager, "agt_1212121212121212"),
        Cancellation(),
    )
    cancelled = cancelled_executor.run(
        _isolated_spec(cancelled_repo, cancelled_manager, "agt_1313131313131313"),
        Cancelled(),
    )

    assert failed.status == "failed"
    assert failed.worktree is not None and failed.worktree.status == "retained_changes"
    assert "SUPER_SECRET_EXCEPTION_TEXT" not in failed.failure_reason
    assert (Path(failed.worktree.path) / "tracked.txt").read_text(encoding="utf-8") == "valuable failure output\n"
    assert cancelled.status == "cancelled"
    assert cancelled.worktree is not None and cancelled.worktree.status == "cleaned"
    assert not Path(cancelled.worktree.path).exists()


def test_initialization_failure_does_not_start_child_and_rolls_back(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    rules = (WorktreeInitRule("copy", "missing.secret", "config.yaml", True),)
    manager = WorktreeManager(WorktreeConfig(initialization=rules))
    called = False

    class Child:
        def run(self, spec, cancellation, workspace_context=None):
            nonlocal called
            called = True
            return TaskOutcome("completed")

    executor = WorktreeTaskExecutor(
        Child(),  # type: ignore[arg-type]
        manager,
        WorkspaceInitializer(manager.git, manager.config),
        WorkspaceContextFactory(ToolContext(repo)),
    )

    outcome = executor.run(
        _isolated_spec(repo, manager, "agt_1414141414141414"),
        Cancellation(),
    )

    assert not called
    assert outcome.status == "failed"
    assert outcome.worktree is not None and outcome.worktree.status == "cleaned"
    assert not Path(outcome.worktree.path).exists()


def test_exit_check_failure_preserves_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager = WorktreeManager(WorktreeConfig(initialization=()))

    class Child:
        def run(self, spec, cancellation, workspace_context=None):
            return TaskOutcome("completed", result="done")

    executor = WorktreeTaskExecutor(
        Child(),  # type: ignore[arg-type]
        manager,
        WorkspaceInitializer(manager.git, manager.config),
        WorkspaceContextFactory(ToolContext(repo)),
    )

    def fail_inspect(identity, environment=None):
        raise RuntimeError("status unavailable")

    manager.inspect = fail_inspect  # type: ignore[method-assign]
    outcome = executor.run(
        _isolated_spec(repo, manager, "agt_1515151515151515"),
        Cancellation(),
    )

    assert outcome.status == "completed"
    assert outcome.worktree is not None and outcome.worktree.status == "cleanup_failed"
    assert Path(outcome.worktree.path).is_dir()
