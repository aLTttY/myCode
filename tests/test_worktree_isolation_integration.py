from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

from mycode.agents.bridge import ParentRequestBridge, freeze_parent_request
from mycode.agents.models import AgentDefinition, AgentSnapshot, TaskOutcome
from mycode.agents.runtime import AgentRoleRuntime
from mycode.agents.tasks import AgentTaskManager
from mycode.agents.tools import AgentTool
from mycode.agents.worktree_executor import WorktreeTaskExecutor
from mycode.providers.base import ChatRequest
from mycode.hooks.events import HookEventFactory
from mycode.tools.files import ReadFileTool
from mycode.tools.registry import create_default_registry
from mycode.types import AgentDelegationConfig, Message, ToolContext, WorktreeConfig
from mycode.worktrees import (
    WorkspaceContextFactory,
    WorkspaceInitializer,
    WorktreeJanitor,
    WorktreeManager,
    initialization_fingerprint,
)

from worktree_testkit import init_repo


def test_concurrent_isolation_two_defined_agents_modify_same_path(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("main-uncommitted\n", encoding="utf-8")
    role = AgentDefinition(
        "builder",
        "build in isolation",
        ("read_file", "write_file"),
        (),
        "inherit",
        4,
        "strict",
        "edit the requested file",
        "project",
        "builder.md",
        "builder-fingerprint",
        "worktree",
    )
    roles = AgentRoleRuntime(
        AgentSnapshot(MappingProxyType({"builder": role}), (), "roles")
    )
    registry = create_default_registry()
    bridge = ParentRequestBridge()
    bridge.publish(
        freeze_parent_request(
            "session",
            "default",
            ChatRequest(
                "system",
                (),
                (Message(role="user", content="parent"),),
                tools=tuple(registry.tool_specs()),
            ),
            registry,
        )
    )
    barrier = threading.Barrier(2)
    observed: dict[str, Path] = {}

    class Child:
        def run(self, spec, cancellation, workspace_context=None):
            assert workspace_context is not None
            workspace = workspace_context.workspace_key
            assert (workspace / "tracked.txt").read_text(encoding="utf-8") == "base\n"
            observed[spec.prompt] = workspace
            barrier.wait(2)
            (workspace / "tracked.txt").write_text(spec.prompt + "\n", encoding="utf-8")
            return TaskOutcome("completed", result=spec.prompt)

    worktree_config = WorktreeConfig(initialization=())
    manager = WorktreeManager(worktree_config)
    main_context = ToolContext(
        repo,
        excluded_roots=(repo / ".mycode" / "worktrees",),
    )
    lifecycle = WorktreeTaskExecutor(
        Child(),  # type: ignore[arg-type]
        manager,
        WorkspaceInitializer(manager.git, worktree_config),
        WorkspaceContextFactory(main_context),
    )
    tasks = AgentTaskManager(lifecycle.run, max_concurrency=2)
    config = AgentDelegationConfig(worktree=worktree_config)
    agent = AgentTool(
        roles,
        bridge,
        tasks,
        lambda: "session",
        lambda: "model",
        config,
        worktree_requests=manager.requests,
    )
    original_cwd = Path.cwd()

    first = agent.run(
        {"type": "defined", "role": "builder", "prompt": "first", "background": True},
        main_context,
    )
    second = agent.run(
        {"type": "defined", "role": "builder", "prompt": "second", "background": True},
        main_context,
    )
    first_details = tasks.wait_task("session", first.data["task_id"], 5)
    second_details = tasks.wait_task("session", second.data["task_id"], 5)

    assert Path.cwd() == original_cwd
    assert observed["first"] != observed["second"]
    assert (observed["first"] / "tracked.txt").read_text(encoding="utf-8") == "first\n"
    assert (observed["second"] / "tracked.txt").read_text(encoding="utf-8") == "second\n"
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "main-uncommitted\n"
    assert first_details.snapshot.worktree is not None
    assert second_details.snapshot.worktree is not None
    assert first_details.snapshot.worktree.status == "retained_changes"
    assert second_details.snapshot.worktree.status == "retained_changes"
    tasks.shutdown(1)


def _active(manager: WorktreeManager, repo: Path, task_id: str):
    request = manager.requests.prepare(
        task_id,
        "builder",
        repo,
        initialization_fingerprint(manager.config.initialization),
    )
    lease = manager.enter(request)
    initialized = WorkspaceInitializer(manager.git, manager.config).initialize(lease)
    active = manager.activate(lease, initialized)
    return active, initialized


def test_concurrent_isolation_context_cache_instruction_memory_prompt_and_hook(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=())
    manager = WorktreeManager(config)
    first, first_init = _active(manager, repo, "agt_aaaaaaaaaaaaaaaa")
    second, second_init = _active(manager, repo, "agt_bbbbbbbbbbbbbbbb")
    for lease, label in ((first, "first"), (second, "second")):
        (lease.workspace_root / "same.txt").write_text(label, encoding="utf-8")
        (lease.workspace_root / "MYCODE.md").write_text(
            f"instruction-{label}\n",
            encoding="utf-8",
        )
        memory = lease.workspace_root / ".mycode" / "memory" / "index.md"
        memory.parent.mkdir(parents=True)
        memory.write_text(f"memory-{label}\n", encoding="utf-8")
    factory = WorkspaceContextFactory(
        ToolContext(repo, excluded_roots=(repo / ".mycode" / "worktrees",))
    )
    first_context = factory.build(first, first_init)
    second_context = factory.build(second, second_init)

    first_read = ReadFileTool().run(
        {"path": "same.txt"},
        first_context.tool_context,
    )
    second_read = ReadFileTool().run(
        {"path": "same.txt"},
        second_context.tool_context,
    )
    first_hook = HookEventFactory(first_context.workspace_key).build("session_start")
    second_hook = HookEventFactory(second_context.workspace_key).build("session_start")

    assert first_context.workspace_key != second_context.workspace_key
    assert first_read.data["content"] == "first"
    assert second_read.data["content"] == "second"
    assert first_context.tool_context.file_read_cache is not second_context.tool_context.file_read_cache
    assert "instruction-first" in first_context.instruction_bundle.content
    assert "instruction-second" not in first_context.instruction_bundle.content
    assert first_context.project_memory_prompt == "memory-first\n"
    assert second_context.project_memory_prompt == "memory-second\n"
    assert str(first_context.workspace_key) in first_context.isolation_instruction.content
    assert str(second_context.workspace_key) in second_context.isolation_instruction.content
    assert first_hook.payload["workspace"] == str(first_context.workspace_key)
    assert second_hook.payload["workspace"] == str(second_context.workspace_key)
    assert not (repo / "same.txt").exists()
    assert manager.exit(first).status == "retained_changes"
    assert manager.exit(second).status == "retained_changes"


def test_exit_dispositions_clean_changes_and_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager = WorktreeManager(WorktreeConfig(initialization=()))
    clean, _ = _active(manager, repo, "agt_cccccccccccccccc")
    changed, _ = _active(manager, repo, "agt_dddddddddddddddd")
    committed, _ = _active(manager, repo, "agt_eeeeeeeeeeeeeeee")
    (changed.workspace_root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (committed.workspace_root / "tracked.txt").write_text("commit\n", encoding="utf-8")
    from worktree_testkit import git

    git(committed.workspace_root, "add", "tracked.txt")
    git(committed.workspace_root, "commit", "-m", "child")

    clean_result = manager.exit(clean)
    changed_result = manager.exit(changed)
    committed_result = manager.exit(committed)

    assert clean_result.status == "cleaned"
    assert changed_result.status == "retained_changes"
    assert committed_result.status == "retained_commits"
    assert not clean_result.identity.worktree_path.exists()
    assert changed_result.identity.worktree_path.exists()
    assert committed_result.identity.worktree_path.exists()
    assert changed_result.identity.base_commit == committed_result.identity.base_commit


def test_delivered_cleanup_uses_only_local_tracking_ref(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager = WorktreeManager(WorktreeConfig(initialization=()))
    lease, _ = _active(manager, repo, "agt_ffffffffffffffff")
    (lease.workspace_root / "tracked.txt").write_text("commit\n", encoding="utf-8")
    from worktree_testkit import git

    git(lease.workspace_root, "add", "tracked.txt")
    git(lease.workspace_root, "commit", "-m", "child")
    retained = manager.exit(lease)
    tip = git(repo, "rev-parse", retained.identity.branch_ref)
    git(
        repo,
        "update-ref",
        "refs/remotes/origin/mewcode/worktree/agt_ffffffffffffffff",
        tip,
    )
    calls: list[tuple[str, ...]] = []
    original_run = manager.git.run

    def recording_run(args, **kwargs):
        calls.append(tuple(args))
        return original_run(args, **kwargs)

    manager.git.run = recording_run  # type: ignore[method-assign]

    disposition = manager.delete(retained.identity)

    assert disposition.status == "cleaned"
    assert not any(call and call[0] in {"fetch", "pull", "push", "merge", "rebase"} for call in calls)


def test_restart_cleanup_keeps_active_changed_and_protected_candidates(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=(), stale_after_seconds=1)
    manager = WorktreeManager(config)
    clean, _ = _active(manager, repo, "agt_0101010101010101")
    changed, _ = _active(manager, repo, "agt_0202020202020202")
    protected, _ = _active(manager, repo, "agt_0303030303030303")
    active, _ = _active(manager, repo, "agt_0404040404040404")
    clean.lock_token.release()
    (changed.workspace_root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    manager.exit(changed)
    (protected.workspace_root / "tracked.txt").write_text("commit\n", encoding="utf-8")
    from worktree_testkit import git

    git(protected.workspace_root, "add", "tracked.txt")
    git(protected.workspace_root, "commit", "-m", "child")
    manager.exit(protected)
    future = datetime.now(timezone.utc) + timedelta(days=2)

    report = WorktreeJanitor(repo, manager, clock=lambda: future).scan_once()

    assert report.cleaned == 1
    assert not clean.workspace_root.exists()
    assert changed.workspace_root.exists()
    assert protected.workspace_root.exists()
    assert active.workspace_root.exists()
    assert manager.exit(active).status == "cleaned"
