from __future__ import annotations

from pathlib import Path

import pytest

from mycode.worktrees.models import WorktreeError
from mycode.worktrees.locking import TargetLock
from mycode.worktrees.paths import validate_managed_name, worktree_path
from worktree_testkit import init_repo


@pytest.mark.parametrize("value", ["tasks/agt_0123456789abcdef", "one", "one/two_3-four"])
def test_accepts_safe_managed_names(value: str) -> None:
    assert validate_managed_name(value) == value


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "a//b", "/absolute", "a\\b", "A", "-bad", "a/../b", "x" * 65],
)
def test_rejects_unsafe_managed_names(value: str) -> None:
    with pytest.raises(WorktreeError):
        validate_managed_name(value)


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    managed = repo / ".mycode" / "worktrees"
    managed.parent.mkdir()
    managed.symlink_to(tmp_path / "outside", target_is_directory=True)
    (tmp_path / "outside").mkdir()

    with pytest.raises(WorktreeError, match="符号链接"):
        worktree_path(repo, "tasks/agt_0123456789abcdef")


def test_rejects_internal_symlink_in_managed_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    actual = repo / "actual-managed"
    actual.mkdir()
    (repo / ".mycode").symlink_to(actual, target_is_directory=True)

    with pytest.raises(WorktreeError, match="符号链接"):
        worktree_path(repo, "tasks/agt_0123456789abcdef")


def test_target_locks_serialize_same_target_and_allow_distinct_targets(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    first = TargetLock(repo, "tasks/agt_0123456789abcdef")
    same = TargetLock(repo, "tasks/agt_0123456789abcdef")
    distinct = TargetLock(repo, "tasks/agt_1111111111111111")

    assert first.acquire(0.2)
    assert not same.acquire(0.02)
    assert distinct.acquire(0.2)
    distinct.release()
    first.release()
    assert same.acquire(0.2)
    same.release()
