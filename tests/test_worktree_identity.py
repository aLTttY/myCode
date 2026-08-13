from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from mycode.types import WorktreeConfig
from mycode.worktrees import WorktreeManager, WorkspaceInitializer, initialization_fingerprint
from mycode.worktrees.identity import IdentityStore
from mycode.worktrees.models import WorktreeError

from worktree_testkit import init_repo


TASK_ID = "agt_1111111111111111"


def test_filesystem_recovery_uses_only_filesystem_and_zero_git(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=())
    first = WorktreeManager(config)
    request = first.requests.prepare(TASK_ID, "reviewer", repo, initialization_fingerprint(()))
    lease = first.enter(request)
    initialized = WorkspaceInitializer(first.git, config).initialize(lease, ())
    active = first.activate(lease, initialized)
    record = repo / ".mycode" / "worktrees" / ".records" / f"{TASK_ID}.json"
    marker = active.workspace_root / ".mycode" / "worktree.json"
    assert stat.S_IMODE(record.stat().st_mode) == 0o600
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600
    active.lock_token.release()

    class NoGit:
        def __getattr__(self, name: str):
            raise AssertionError(f"recovery called git: {name}")

    recovered_manager = WorktreeManager(config, git=NoGit())  # type: ignore[arg-type]
    recovered_request = recovered_manager.requests.prepare(
        TASK_ID,
        "reviewer",
        repo,
        initialization_fingerprint(()),
    )
    recovered = recovered_manager.enter(recovered_request)

    assert recovered.recovered
    assert recovered.identity == active.identity
    recovered.lock_token.release()


def test_recovery_rejects_mismatched_marker_without_writing(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=())
    manager = WorktreeManager(config)
    request = manager.requests.prepare(TASK_ID, "reviewer", repo, initialization_fingerprint(()))
    lease = manager.enter(request)
    active = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease, ()),
    )
    active.lock_token.release()
    marker = active.workspace_root / ".mycode" / "worktree.json"
    value = json.loads(marker.read_text(encoding="utf-8"))
    value["base_commit"] = "0" * 40
    marker.write_text(json.dumps(value), encoding="utf-8")
    before = marker.read_bytes()

    with pytest.raises(WorktreeError, match="身份"):
        IdentityStore().recover(repo, TASK_ID, "reviewer", initialization_fingerprint(()))

    assert marker.read_bytes() == before


def test_identity_unknown_field_is_rejected(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=())
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "reviewer",
        repo,
        initialization_fingerprint(()),
    )
    lease = manager.enter(request)
    active = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease, ()),
    )
    active.lock_token.release()
    record = repo / ".mycode" / "worktrees" / ".records" / f"{TASK_ID}.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload["future_field"] = True
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorktreeError, match="schema"):
        IdentityStore().read_primary(repo, TASK_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("managed_name", "tasks/agt_aaaaaaaaaaaaaaaa"),
        ("branch_ref", "refs/heads/main"),
        ("base_commit", "not-a-commit"),
        ("base_ref", "refs/tags/main"),
        ("repository_id", "0" * 40),
        ("initialization_fingerprint", "0" * 40),
    ],
)
def test_identity_parser_rejects_noncanonical_system_fields(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    repo = init_repo(tmp_path / "repo")
    config = WorktreeConfig(initialization=())
    manager = WorktreeManager(config)
    request = manager.requests.prepare(
        TASK_ID,
        "reviewer",
        repo,
        initialization_fingerprint(()),
    )
    lease = manager.enter(request)
    active = manager.activate(
        lease,
        WorkspaceInitializer(manager.git, config).initialize(lease, ()),
    )
    active.lock_token.release()
    record = repo / ".mycode" / "worktrees" / ".records" / f"{TASK_ID}.json"
    payload = json.loads(record.read_text(encoding="utf-8"))
    payload[field] = value
    record.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorktreeError):
        IdentityStore().read_primary(repo, TASK_ID)
