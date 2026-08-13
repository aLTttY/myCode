from __future__ import annotations

import filecmp
import os
import shutil
from pathlib import Path
from types import MappingProxyType

from mycode.types import WorktreeConfig, WorktreeInitRule

from .git import GitRunner
from .models import (
    InitializationResult,
    InitializedPath,
    WorktreeDiagnostic,
    WorktreeError,
    WorktreeLease,
)


class WorkspaceInitializer:
    def __init__(self, git: GitRunner, config: WorktreeConfig) -> None:
        self.git = git
        self.config = config

    def initialize(
        self,
        lease: WorktreeLease,
        rules: tuple[WorktreeInitRule, ...] | None = None,
    ) -> InitializationResult:
        configured = self.config.initialization if rules is None else rules
        if lease.recovered:
            return self._verify_recovered(lease)
        manifest: list[InitializedPath] = []
        diagnostics: list[WorktreeDiagnostic] = []
        created: list[Path] = []
        environment: dict[str, str] = dict(lease.process_environment)
        try:
            for index, rule in enumerate(configured):
                source = _safe_source(lease.identity.main_workspace, rule.source)
                if not source.exists():
                    if rule.required:
                        raise WorktreeError("required_source_missing", f"初始化规则 {index} 的必需源不存在。")
                    diagnostics.append(
                        WorktreeDiagnostic("warning", "optional_source_missing", index, "可选初始化源不存在，已跳过。")
                    )
                    continue
                item = InitializedPath(rule.action, rule.source, rule.target, rule.required)
                if rule.action == "hooks":
                    if not source.is_dir() or source.is_symlink():
                        raise WorktreeError("invalid_hooks_source", f"初始化规则 {index} 的 hooks 源无效。")
                    environment.update(_git_config_overlay(environment, "core.hooksPath", str(source.resolve(strict=True))))
                    manifest.append(item)
                    continue
                assert rule.target is not None
                target = _safe_target(lease.workspace_root, rule.target)
                ignore_probe = (
                    f"{rule.target}/.mewcode-ignore-probe"
                    if source.is_dir()
                    else rule.target
                )
                if not self.git.check_ignored(lease.workspace_root, ignore_probe, environment):
                    raise WorktreeError("target_not_ignored", f"初始化规则 {index} 的目标未被 Git ignore。")
                if target.exists() or target.is_symlink():
                    if _matches(rule.action, source, target):
                        manifest.append(item)
                        continue
                    raise WorktreeError("target_conflict", f"初始化规则 {index} 的目标已存在且不匹配。")
                target.parent.mkdir(parents=True, exist_ok=True)
                created.append(target)
                if rule.action == "symlink":
                    target.symlink_to(source.resolve(strict=True), target_is_directory=source.is_dir())
                else:
                    self._copy(source, target)
                manifest.append(item)
        except Exception:
            for target in reversed(created):
                _remove_created(target)
                _prune_empty_parents(target.parent, lease.workspace_root)
            raise
        return InitializationResult(
            tuple(manifest),
            MappingProxyType(environment),
            tuple(diagnostics),
        )

    def _verify_recovered(self, lease: WorktreeLease) -> InitializationResult:
        environment: dict[str, str] = dict(lease.process_environment)
        for index, item in enumerate(lease.identity.initialization_manifest):
            source = _safe_source(lease.identity.main_workspace, item.source)
            if not source.exists():
                raise WorktreeError("recovery_source_missing", f"恢复规则 {index} 的初始化源已缺失。")
            if item.action == "hooks":
                if not source.is_dir() or source.is_symlink():
                    raise WorktreeError("recovery_hooks_mismatch", f"恢复规则 {index} 的 hooks 源不匹配。")
                environment.update(_git_config_overlay(environment, "core.hooksPath", str(source.resolve(strict=True))))
                continue
            assert item.target is not None
            target = _safe_target(lease.workspace_root, item.target)
            if not _matches(item.action, source, target):
                raise WorktreeError("recovery_target_mismatch", f"恢复规则 {index} 的目标不匹配。")
        return InitializationResult(
            lease.identity.initialization_manifest,
            MappingProxyType(environment),
            lease.initialization_diagnostics,
        )

    def _copy(self, source: Path, target: Path) -> None:
        if source.is_symlink():
            raise WorktreeError("copy_symlink", "复制初始化源不能是符号链接。")
        if source.is_file():
            if source.stat().st_size > self.config.copy_max_bytes:
                raise WorktreeError("copy_limit", "复制初始化源超过字节上限。")
            shutil.copy2(source, target, follow_symlinks=False)
            return
        if not source.is_dir():
            raise WorktreeError("copy_source_type", "复制初始化源类型无效。")
        files = 0
        total = 0
        for path in source.rglob("*"):
            if path.is_symlink():
                raise WorktreeError("copy_symlink", "复制目录包含符号链接。")
            if path.is_file():
                files += 1
                total += path.stat().st_size
                if files > self.config.copy_max_files or total > self.config.copy_max_bytes:
                    raise WorktreeError("copy_limit", "复制目录超过文件数或字节上限。")
        shutil.copytree(source, target, symlinks=False)


def initialized_path_matches(lease_identity, item: InitializedPath) -> bool:
    if item.action == "hooks":
        return True
    if item.target is None:
        return False
    try:
        source = _safe_source(lease_identity.main_workspace, item.source)
        target = _safe_target(lease_identity.worktree_path, item.target)
        return source.exists() and _matches(item.action, source, target)
    except (OSError, WorktreeError):
        return False


def _safe_source(root: Path, relative: str) -> Path:
    return _safe_relative(root, relative, source=True)


def _safe_target(root: Path, relative: str) -> Path:
    return _safe_relative(root, relative, source=False)


def _safe_relative(root: Path, relative: str, *, source: bool) -> Path:
    if "\\" in relative or Path(relative).is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise WorktreeError("unsafe_init_path", "初始化规则路径不安全。")
    boundary = root.resolve(strict=True)
    target = root.joinpath(*relative.split("/"))
    existing = target.parent if target.is_symlink() and not source else target
    while not existing.exists() and existing != root:
        existing = existing.parent
    try:
        existing.resolve(strict=True).relative_to(boundary)
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorktreeError("init_path_escape", "初始化路径逃离工作区。") from exc
    if source and target.is_symlink():
        resolved = target.resolve(strict=True)
        try:
            resolved.relative_to(boundary)
        except ValueError as exc:
            raise WorktreeError("init_symlink_escape", "初始化源符号链接逃离工作区。") from exc
    return target


def _matches(action: str, source: Path, target: Path) -> bool:
    if action == "symlink":
        try:
            return target.is_symlink() and target.resolve(strict=True) == source.resolve(strict=True)
        except OSError:
            return False
    if not target.exists() or target.is_symlink() or source.is_symlink():
        return False
    if source.is_file() and target.is_file():
        return filecmp.cmp(source, target, shallow=False)
    if source.is_dir() and target.is_dir():
        comparison = filecmp.dircmp(source, target)
        if comparison.left_only or comparison.right_only or comparison.funny_files:
            return False
        if any(not filecmp.cmp(source / name, target / name, shallow=False) for name in comparison.common_files):
            return False
        return all(_matches("copy", source / name, target / name) for name in comparison.common_dirs)
    return False


def _git_config_overlay(existing: dict[str, str], key: str, value: str) -> dict[str, str]:
    try:
        count = int(existing.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        count = 0
    return {
        "GIT_CONFIG_COUNT": str(count + 1),
        f"GIT_CONFIG_KEY_{count}": key,
        f"GIT_CONFIG_VALUE_{count}": value,
    }


def _remove_created(target: Path) -> None:
    try:
        if target.is_symlink() or target.is_file():
            target.unlink(missing_ok=True)
        elif target.is_dir():
            shutil.rmtree(target)
    except OSError:
        pass


def _prune_empty_parents(parent: Path, boundary: Path) -> None:
    root = boundary.resolve(strict=True)
    current = parent
    while current != root:
        try:
            current.resolve(strict=True).relative_to(root)
            current.rmdir()
        except (OSError, RuntimeError, ValueError):
            return
        current = current.parent
