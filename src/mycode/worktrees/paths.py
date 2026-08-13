from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .models import WorktreeError


MANAGED_ROOT = Path(".mycode/worktrees")
NAME_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TASK_ID = re.compile(r"^agt_[a-f0-9]{16}$")
MAX_MANAGED_NAME = 200


def validate_managed_name(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_MANAGED_NAME:
        raise WorktreeError("invalid_name", "Worktree 受管名称为空或过长。")
    if "\\" in value or Path(value).is_absolute():
        raise WorktreeError("invalid_name", "Worktree 受管名称不能是绝对路径或包含反斜杠。")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or NAME_SEGMENT.fullmatch(part) is None for part in parts):
        raise WorktreeError("invalid_name", "Worktree 受管名称包含非法路径段。")
    return value


def validate_task_id(task_id: str) -> str:
    if TASK_ID.fullmatch(task_id) is None:
        raise WorktreeError("invalid_task_id", "Worktree 任务 ID 非法。")
    return task_id


def managed_name_for_task(task_id: str) -> str:
    return validate_managed_name(f"tasks/{validate_task_id(task_id)}")


def branch_ref_for_task(task_id: str) -> str:
    validate_task_id(task_id)
    return f"refs/heads/mewcode/worktree/{task_id}"


def worktree_root(main_workspace: Path) -> Path:
    workspace = main_workspace.resolve(strict=True)
    return workspace / MANAGED_ROOT


def worktree_path(main_workspace: Path, managed_name: str) -> Path:
    root = worktree_root(main_workspace)
    value = validate_managed_name(managed_name)
    candidate = root.joinpath(*value.split("/"))
    _assert_inside(candidate, root, allow_missing=True)
    return candidate


def record_path(main_workspace: Path, task_id: str) -> Path:
    return worktree_root(main_workspace) / ".records" / f"{validate_task_id(task_id)}.json"


def marker_path(target: Path) -> Path:
    return target / ".mycode" / "worktree.json"


def lock_path(main_workspace: Path, managed_name: str) -> Path:
    digest = hashlib.sha256(validate_managed_name(managed_name).encode("utf-8")).hexdigest()
    return worktree_root(main_workspace) / ".locks" / f"{digest}.lock"


def assert_managed_target(main_workspace: Path, target: Path, managed_name: str) -> Path:
    expected = worktree_path(main_workspace, managed_name)
    lexical_target = Path(os.path.abspath(target))
    lexical_expected = Path(os.path.abspath(expected))
    if lexical_target != lexical_expected:
        raise WorktreeError("path_mismatch", "Worktree 目标路径与受管身份不匹配。")
    _assert_inside(target, worktree_root(main_workspace), allow_missing=not target.exists())
    return target


def _assert_inside(candidate: Path, root: Path, *, allow_missing: bool) -> None:
    try:
        lexical = Path(os.path.abspath(candidate))
        root_lexical = Path(os.path.abspath(root))
        relative = lexical.relative_to(root_lexical)
    except (OSError, ValueError) as exc:
        raise WorktreeError("path_escape", "Worktree 路径逃离专用根目录。") from exc
    if relative == Path("."):
        raise WorktreeError("root_target", "不能把 Worktree 专用根目录作为目标。")
    # Resolve the longest existing prefix so an existing symlink cannot redirect
    # creation or deletion outside the fixed managed root.
    repository_lexical = root_lexical.parent.parent
    cursor = repository_lexical
    for part in lexical.relative_to(repository_lexical).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise WorktreeError(
                "symlink_escape",
                "Worktree 受管路径不能经过符号链接。",
            )
        if not cursor.exists():
            break
    existing = lexical
    while not existing.exists() and existing != repository_lexical:
        existing = existing.parent
    try:
        resolved_repository = repository_lexical.resolve(strict=True)
        if root_lexical.is_symlink():
            raise WorktreeError("symlink_escape", "Worktree 专用根目录不能是符号链接。")
        resolved_existing = existing.resolve(strict=True)
        resolved_existing.relative_to(resolved_repository)
        if root_lexical.exists():
            root_lexical.resolve(strict=True).relative_to(resolved_repository)
    except WorktreeError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorktreeError("symlink_escape", "Worktree 路径经符号链接逃离专用根目录。") from exc
    if not allow_missing and not lexical.exists():
        raise WorktreeError("missing_target", "Worktree 目标目录不存在。")


def filesystem_repository_id(main_workspace: Path) -> str:
    common = common_git_directory(main_workspace)
    stat = common.stat()
    identity = f"{common}\0{stat.st_dev}\0{stat.st_ino}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def common_git_directory(main_workspace: Path) -> Path:
    workspace = main_workspace.resolve(strict=True)
    git_entry = workspace / ".git"
    if git_entry.is_dir():
        common = git_entry.resolve(strict=True)
    elif git_entry.is_file():
        text = git_entry.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir: "):
            raise WorktreeError("invalid_repository", "主工作区 .git 指针无效。")
        gitdir = Path(text[8:])
        common = (workspace / gitdir).resolve(strict=True) if not gitdir.is_absolute() else gitdir.resolve(strict=True)
        common_file = common / "commondir"
        if common_file.is_file():
            relative = Path(common_file.read_text(encoding="utf-8").strip())
            common = (common / relative).resolve(strict=True)
    else:
        raise WorktreeError("not_repository", "主工作区不是 Git 仓库。")
    return common
