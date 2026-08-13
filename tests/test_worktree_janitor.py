from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import threading
from pathlib import Path

from mycode.types import WorktreeConfig
from mycode.worktrees import WorktreeJanitor, WorktreeManager, WorkspaceInitializer, initialization_fingerprint

from worktree_testkit import git, init_repo


def _retained_commit(repo: Path, task_id: str):
    config = WorktreeConfig(
        initialization=(),
        git_timeout_seconds=0.2,
        cleanup_interval_seconds=0.05,
        stale_after_seconds=1,
    )
    manager = WorktreeManager(config)
    request = manager.requests.prepare(task_id, "builder", repo, initialization_fingerprint(()))
    lease = manager.enter(request)
    lease = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease, ()),
    )
    (lease.workspace_root / "tracked.txt").write_text("child\n", encoding="utf-8")
    git(lease.workspace_root, "add", "tracked.txt")
    git(lease.workspace_root, "commit", "-m", "child")
    disposition = manager.exit(lease)
    assert disposition.status == "retained_commits"
    return manager, disposition.identity


def test_janitor_deletes_only_stale_delivered_candidate(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, identity = _retained_commit(repo, "agt_4444444444444444")
    git(repo, "merge", "--ff-only", identity.branch_ref)
    future = datetime.now(timezone.utc) + timedelta(days=2)
    janitor = WorktreeJanitor(repo, manager, clock=lambda: future)

    report = janitor.scan_once()

    assert report.cleaned == 1
    assert report.failed == 0
    assert not identity.worktree_path.exists()


def test_janitor_preserves_stale_uncommitted_change(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=(), stale_after_seconds=1)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        "agt_5555555555555555", "builder", repo, initialization_fingerprint(())
    )
    lease = manager.enter(request)
    lease = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease, ()),
    )
    (lease.workspace_root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    retained = manager.exit(lease)
    future = datetime.now(timezone.utc) + timedelta(days=2)

    report = WorktreeJanitor(repo, manager, clock=lambda: future).scan_once()

    assert report.cleaned == 0
    assert report.skipped == 1
    assert retained.identity.worktree_path.exists()


def test_protected_delete_accepts_same_name_remote_tracking_ref(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, identity = _retained_commit(repo, "agt_6666666666666666")
    tip = git(repo, "rev-parse", identity.branch_ref)
    remote_ref = "refs/remotes/origin/mewcode/worktree/agt_6666666666666666"
    git(repo, "update-ref", remote_ref, tip)

    disposition = manager.delete(identity)

    assert disposition.status == "cleaned"


def test_janitor_reports_corrupt_record_without_touching_foreign_directory(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    records = repo / ".mycode" / "worktrees" / ".records"
    records.mkdir(parents=True)
    (records / "agt_7777777777777777.json").write_text("{broken", encoding="utf-8")
    foreign = repo / ".mycode" / "worktrees" / "foreign"
    foreign.mkdir(parents=True)
    (foreign / "keep.txt").write_text("keep", encoding="utf-8")
    manager = WorktreeManager(WorktreeConfig(initialization=()))

    report = WorktreeJanitor(repo, manager).scan_once()

    assert any(item.code == "record_corrupt" for item in report.diagnostics)
    assert (foreign / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_janitor_skips_active_lease_lock(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=(), stale_after_seconds=1)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        "agt_8888888888888888", "builder", repo, initialization_fingerprint(())
    )
    lease = manager.enter(request)
    lease = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease, ()),
    )
    future = datetime.now(timezone.utc) + timedelta(days=2)

    report = WorktreeJanitor(repo, manager, clock=lambda: future).scan_once()

    assert report.cleaned == 0
    assert report.skipped == 1
    assert lease.workspace_root.exists()
    assert manager.exit(lease).status == "cleaned"


def test_candidate_repository_mismatch_is_rejected_before_lock_creation(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    records = repo / ".mycode" / "worktrees" / ".records"
    records.mkdir(parents=True)
    task_id = "agt_9999999999999999"
    fake_workspace = tmp_path / "foreign-repository"
    payload = {
        "schema_version": 1,
        "repository_id": "0" * 64,
        "task_id": task_id,
        "role_name": "builder",
        "managed_name": f"tasks/{task_id}",
        "main_workspace": str(fake_workspace),
        "worktree_path": str(fake_workspace / ".mycode/worktrees/tasks" / task_id),
        "branch_ref": f"refs/heads/mewcode/worktree/{task_id}",
        "base_commit": "0" * 40,
        "base_ref": "refs/heads/main",
        "expected_gitdir": str(fake_workspace / ".git/worktrees/fake"),
        "initialization_fingerprint": "0" * 64,
        "initialization_manifest": [],
        "lifecycle_state": "retained",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    }
    (records / f"{task_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    manager = WorktreeManager(WorktreeConfig(initialization=()))

    report = WorktreeJanitor(repo, manager).scan_once()

    assert report.cleaned == 0
    assert any(
        item.code == "record_repository_mismatch" for item in report.diagnostics
    )
    assert not fake_workspace.exists()


def test_periodic_janitor_survives_one_scan_failure_and_closes_bounded(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(
        initialization=(),
        cleanup_interval_seconds=0.02,
    )
    janitor = WorktreeJanitor(repo, WorktreeManager(config))
    completed_after_failure = threading.Event()
    calls = 0

    def flaky_scan():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected scan failure")
        completed_after_failure.set()

    janitor.scan_once = flaky_scan  # type: ignore[method-assign]
    janitor.start()

    assert completed_after_failure.wait(1)
    janitor.close(0.5)
    assert calls >= 2
    assert janitor._thread is not None and not janitor._thread.is_alive()
