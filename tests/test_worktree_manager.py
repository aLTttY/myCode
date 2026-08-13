from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mycode.types import WorktreeConfig, WorktreeInitRule
from mycode.worktrees import WorktreeManager, WorkspaceInitializer, initialization_fingerprint
from mycode.worktrees.identity import IdentityStore
from mycode.worktrees.git import GitRunner, parse_worktree_list
from mycode.worktrees.models import WorktreeError

from worktree_testkit import git, init_repo


TASK_ID = "agt_0123456789abcdef"


def _active(repo: Path):
    config = WorktreeConfig(initialization=())
    manager = WorktreeManager(config)
    request = manager.requests.prepare(TASK_ID, "reviewer", repo, initialization_fingerprint(()))
    lease = manager.enter(request)
    initialized = WorkspaceInitializer(manager.git, config).initialize(lease, ())
    return manager, manager.activate(lease, initialized)


def test_creates_and_cleans_unchanged_worktree(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, lease = _active(repo)

    assert lease.workspace_root.is_dir()
    assert lease.workspace_root != repo
    assert git(repo, "rev-parse", "HEAD") == lease.identity.base_commit
    assert manager.inspect(lease.identity).safe_for_task_exit

    disposition = manager.exit(lease)

    assert disposition.status == "cleaned"
    assert not disposition.identity.worktree_path.exists()
    assert git(repo, "branch", "--list", "mewcode/worktree/*") == ""


def test_retains_changes_and_then_allows_clean_delete(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, lease = _active(repo)
    (lease.workspace_root / "tracked.txt").write_text("changed\n", encoding="utf-8")

    retained = manager.exit(lease)

    assert retained.status == "retained_changes"
    assert retained.identity.worktree_path.is_dir()
    (retained.identity.worktree_path / "tracked.txt").write_text("base\n", encoding="utf-8")
    deleted = manager.delete(retained.identity)
    assert deleted.status == "cleaned"


def test_task_exit_retains_any_new_commit(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, lease = _active(repo)
    (lease.workspace_root / "tracked.txt").write_text("committed\n", encoding="utf-8")
    git(lease.workspace_root, "add", "tracked.txt")
    git(lease.workspace_root, "commit", "-m", "child")

    retained = manager.exit(lease)

    assert retained.status == "retained_commits"
    assert retained.inspection is not None
    assert retained.inspection.new_commits
    assert manager.delete(retained.identity).status == "retained_commits"


def test_task_exit_retains_arbitrary_ignored_file(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, lease = _active(repo)
    ignored_file = lease.workspace_root / "agent-notes.log"
    ignored_file.write_text("must not be discarded\n", encoding="utf-8")

    retained = manager.exit(lease)

    assert retained.status == "retained_changes"
    assert ignored_file.read_text(encoding="utf-8") == "must not be discarded\n"
    ignored_file.unlink()
    assert manager.delete(retained.identity).status == "cleaned"


def test_task_exit_retains_modified_ignored_initialization_copy(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "config.yaml").write_text("source: main\n", encoding="utf-8")
    rules = (WorktreeInitRule("copy", "config.yaml", "config.yaml", True),)
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "reviewer",
        repo,
        initialization_fingerprint(rules),
    )
    lease = manager.enter(request)
    active = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease),
    )
    copied = active.workspace_root / "config.yaml"
    copied.write_text("agent: changed\n", encoding="utf-8")

    retained = manager.exit(active)

    assert retained.status == "retained_changes"
    assert copied.read_text(encoding="utf-8") == "agent: changed\n"
    copied.write_text("source: main\n", encoding="utf-8")
    assert manager.delete(retained.identity).status == "cleaned"


def test_identity_write_failure_rolls_back_created_resources(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")

    class FailingIdentityStore(IdentityStore):
        def write(self, identity) -> None:
            super().write(identity)
            raise WorktreeError("injected_failure", "injected")

    manager = WorktreeManager(
        WorktreeConfig(initialization=()),
        identities=FailingIdentityStore(),
    )
    request = manager.requests.prepare(
        TASK_ID,
        "reviewer",
        repo,
        initialization_fingerprint(()),
    )

    with pytest.raises(WorktreeError, match="injected"):
        manager.enter(request)

    assert not request.worktree_path.exists()
    assert not (repo / ".mycode" / "worktrees" / ".records" / f"{TASK_ID}.json").exists()
    assert git(repo, "branch", "--list", "mewcode/worktree/*") == ""


def test_ref_delete_failure_removes_stale_identity_but_preserves_branch(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, lease = _active(repo)

    def fail_delete_ref(workspace, ref, expected_old):
        raise WorktreeError("injected_failure", "injected")

    manager.git.delete_ref = fail_delete_ref  # type: ignore[method-assign]

    disposition = manager.exit(lease)

    record = repo / ".mycode" / "worktrees" / ".records" / f"{TASK_ID}.json"
    assert disposition.status == "cleanup_failed"
    assert not disposition.identity.worktree_path.exists()
    assert not record.exists()
    assert git(repo, "branch", "--list", "mewcode/worktree/*") != ""


def test_delete_identity_mismatch_does_not_repair_or_remove_target(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    manager, lease = _active(repo)
    lease.lock_token.release()
    marker = lease.workspace_root / ".mycode" / "worktree.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["role_name"] = "tampered"
    marker.write_text(json.dumps(payload), encoding="utf-8")
    before = marker.read_bytes()

    disposition = manager.delete(lease.identity)

    assert disposition.status == "cleanup_failed"
    assert marker.read_bytes() == before
    assert lease.workspace_root.is_dir()


@pytest.mark.parametrize(
    "remaining_ignore",
    [
        ".mycode/worktree.json\n",
        ".mycode/worktrees/\n",
    ],
)
def test_creation_requires_managed_paths_to_be_git_ignored(
    tmp_path: Path,
    remaining_ignore: str,
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(remaining_ignore, encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "remove one managed ignore")
    manager = WorktreeManager(WorktreeConfig(initialization=()))

    with pytest.raises(WorktreeError, match="忽略"):
        manager.requests.prepare(
            TASK_ID,
            "reviewer",
            repo,
            initialization_fingerprint(()),
        )

    assert not (repo / ".mycode" / "worktrees" / "tasks" / TASK_ID).exists()


def test_git_runner_timeout_and_malformed_porcelain_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 0.01)

    monkeypatch.setattr("mycode.worktrees.git.subprocess.run", timeout)
    with pytest.raises(WorktreeError) as caught:
        GitRunner(0.01).run(("status",), cwd=tmp_path)
    assert caught.value.code == "git_timeout"

    with pytest.raises(WorktreeError, match="重复字段"):
        parse_worktree_list(
            b"worktree /tmp/one\0worktree /tmp/two\0HEAD " + b"0" * 40 + b"\0\0"
        )


def test_prepared_request_keeps_call_time_head_after_main_branch_advances(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    manager = WorktreeManager(WorktreeConfig(initialization=()))
    request = manager.requests.prepare(
        TASK_ID,
        "reviewer",
        repo,
        initialization_fingerprint(()),
    )
    (repo / "tracked.txt").write_text("new main commit\n", encoding="utf-8")
    (repo / "main-only.tmp").write_text("untracked main\n", encoding="utf-8")
    git(repo, "add", "tracked.txt")
    git(repo, "commit", "-m", "advance main")

    lease = manager.enter(request)
    active = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, manager.config).initialize(lease, ()),
    )

    assert active.identity.base_commit == request.base_commit
    assert git(repo, "rev-parse", "HEAD") != request.base_commit
    assert (active.workspace_root / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert not (active.workspace_root / "main-only.tmp").exists()
    assert manager.exit(active).status == "cleaned"
