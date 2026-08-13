from __future__ import annotations

import os
from pathlib import Path

import pytest

from mycode.types import WorktreeConfig, WorktreeInitRule
from mycode.worktrees import WorktreeManager, WorkspaceInitializer, initialization_fingerprint
from mycode.worktrees.models import WorktreeError

from worktree_testkit import init_repo


TASK_ID = "agt_2222222222222222"


def test_copy_symlink_hooks_and_recovery_are_idempotent(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "config.yaml").write_text("secret: local\n", encoding="utf-8")
    dependency = repo / ".venv"
    dependency.mkdir()
    (dependency / "marker").write_text("large", encoding="utf-8")
    rules = (
        WorktreeInitRule("copy", "config.yaml", "config.yaml", True),
        WorktreeInitRule("symlink", ".venv", ".venv", True),
        WorktreeInitRule("hooks", ".git/hooks", None, True),
    )
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(TASK_ID, "builder", repo, initialization_fingerprint(rules))
    lease = manager.enter(request)

    result = WorkspaceInitializer(manager.git, config).initialize(lease)
    active = manager.activate(lease, result)

    assert (active.workspace_root / "config.yaml").read_text(encoding="utf-8") == "secret: local\n"
    assert (active.workspace_root / ".venv").is_symlink()
    assert active.process_environment["GIT_CONFIG_KEY_0"] == "core.hooksPath"
    copied_stat = (active.workspace_root / "config.yaml").stat().st_mtime_ns
    active.lock_token.release()

    recovered_request = manager.requests.prepare(
        TASK_ID, "builder", repo, initialization_fingerprint(rules)
    )
    recovered = manager.enter(recovered_request)
    again = WorkspaceInitializer(manager.git, config).initialize(recovered)
    assert (recovered.workspace_root / "config.yaml").stat().st_mtime_ns == copied_stat
    assert again.manifest == active.identity.initialization_manifest
    recovered.lock_token.release()


def test_required_missing_source_blocks_initialization(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    rules = (WorktreeInitRule("copy", "missing.local", "missing.local", True),)
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(TASK_ID, "builder", repo, initialization_fingerprint(rules))
    lease = manager.enter(request)

    with pytest.raises(WorktreeError, match="必需源"):
        WorkspaceInitializer(manager.git, config).initialize(lease)

    disposition = manager.abort_initialization(lease)
    assert disposition.status == "cleaned"


def test_optional_missing_source_is_redacted_diagnostic(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    rules = (WorktreeInitRule("copy", "missing-local-secret", "config.yaml"),)
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "builder",
        repo,
        initialization_fingerprint(rules),
    )
    lease = manager.enter(request)

    initialized = WorkspaceInitializer(manager.git, config).initialize(lease)

    assert initialized.manifest == ()
    assert initialized.diagnostics[0].code == "optional_source_missing"
    assert "missing-local-secret" not in initialized.diagnostics[0].message
    active = manager.activate(lease, initialized)
    assert manager.exit(active).status == "cleaned"


def test_copy_rejects_source_symlink_without_leaking_or_overwriting(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    outside = tmp_path / "outside-secret"
    outside.write_text("SECRET_CONTENT", encoding="utf-8")
    (repo / "linked-secret").symlink_to(outside)
    rules = (WorktreeInitRule("copy", "linked-secret", "config.yaml", True),)
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "builder",
        repo,
        initialization_fingerprint(rules),
    )
    lease = manager.enter(request)

    with pytest.raises(WorktreeError) as caught:
        WorkspaceInitializer(manager.git, config).initialize(lease)

    assert "SECRET_CONTENT" not in str(caught.value)
    assert not (lease.workspace_root / "config.yaml").exists()
    manager.abort_initialization(lease)


def test_secret_content_is_not_persisted_in_identity(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    secret = "UNIQUE_SUPER_SECRET_VALUE"
    (repo / "config.yaml").write_text(secret, encoding="utf-8")
    rules = (WorktreeInitRule("copy", "config.yaml", "config.yaml", True),)
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(TASK_ID, "builder", repo, initialization_fingerprint(rules))
    lease = manager.enter(request)
    active = manager.activate(lease, WorkspaceInitializer(manager.git, config).initialize(lease))

    record = repo / ".mycode" / "worktrees" / ".records" / f"{TASK_ID}.json"
    assert secret.encode() not in record.read_bytes()
    assert secret.encode() not in (active.workspace_root / ".mycode" / "worktree.json").read_bytes()
    active.lock_token.release()


def test_failed_directory_copy_removes_partial_target(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    source = repo / "local-cache"
    source.mkdir()
    (source / "one").write_text("1", encoding="utf-8")
    (source / "two").write_text("2", encoding="utf-8")
    with (repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("local-copy/\n")
    # The ignore rule must be part of the Worktree baseline.
    from worktree_testkit import git

    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore local copy")
    rules = (WorktreeInitRule("copy", "local-cache", "local-copy", True),)
    config = WorktreeConfig(initialization=rules, copy_max_files=1)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(TASK_ID, "builder", repo, initialization_fingerprint(rules))
    lease = manager.enter(request)

    with pytest.raises(WorktreeError, match="上限"):
        WorkspaceInitializer(manager.git, config).initialize(lease)

    assert not (lease.workspace_root / "local-copy").exists()
    manager.abort_initialization(lease)


def test_recovery_initialization_mismatch_preserves_modified_ignored_file(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "config.yaml").write_text("source: original\n", encoding="utf-8")
    rules = (WorktreeInitRule("copy", "config.yaml", "config.yaml", True),)
    config = WorktreeConfig(initialization=rules)
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "builder",
        repo,
        initialization_fingerprint(rules),
    )
    lease = manager.enter(request)
    active = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease),
    )
    copied = active.workspace_root / "config.yaml"
    copied.write_text("agent: valuable change\n", encoding="utf-8")
    active.lock_token.release()

    recovered_request = manager.requests.prepare(
        TASK_ID,
        "builder",
        repo,
        initialization_fingerprint(rules),
    )
    recovered = manager.enter(recovered_request)
    with pytest.raises(WorktreeError, match="不匹配"):
        WorkspaceInitializer(manager.git, config).initialize(recovered)

    disposition = manager.abort_initialization(recovered)

    assert disposition.status == "cleanup_failed"
    assert copied.read_text(encoding="utf-8") == "agent: valuable change\n"
    assert disposition.identity.worktree_path.is_dir()
