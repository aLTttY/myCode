from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

from mycode.types import WorktreeConfig
from mycode.worktrees.git import GitRunner
from mycode.worktrees.identity import read_gitdir_pointer
from mycode.worktrees.models import WorktreeError
from mycode.worktrees.paths import filesystem_repository_id

from .models import TeamError, TeamMemberSnapshot, TeamWorktreeIdentity, utc_now
from .paths import validate_member_name, validate_team_name


def managed_name_for_member(team_name: str, member_name: str, member_id: str) -> str:
    team = validate_team_name(team_name)
    member = validate_member_name(member_name)
    digest = hashlib.sha256(member_id.encode("utf-8")).hexdigest()[:10]
    return f"teams/{team}/{member}-{digest}"


def branch_ref_for_member(team_name: str, member_id: str) -> str:
    team = validate_team_name(team_name)
    digest = hashlib.sha256(member_id.encode("utf-8")).hexdigest()[:16]
    return f"refs/heads/mewcode/team/{team}/{digest}"


class TeamWorktreeManager:
    def __init__(self, config: WorktreeConfig | None = None, *, git: GitRunner | None = None) -> None:
        self.config = config or WorktreeConfig()
        self.git = git or GitRunner(self.config.git_timeout_seconds)

    def provision(
        self,
        team_name: str,
        member_id: str,
        member_name: str,
        main_workspace: Path,
        repository_id: str,
        initialization_fingerprint: str,
        *,
        writable: bool,
    ) -> TeamWorktreeIdentity | None:
        workspace = main_workspace.resolve(strict=True)
        if filesystem_repository_id(workspace) != repository_id:
            raise TeamError("repository_mismatch", "成员 Worktree 仓库身份不匹配。")
        if not writable:
            return None
        managed_name = managed_name_for_member(team_name, member_name, member_id)
        target = workspace / ".mycode" / "worktrees" / managed_name
        branch_ref = branch_ref_for_member(team_name, member_id)
        if target.exists() or target.is_symlink() or self.git.ref_exists(workspace, branch_ref):
            raise TeamError("worktree_conflict", "成员长期 Worktree 路径或分支已存在。")
        target.parent.mkdir(parents=True, exist_ok=True)
        base_commit = self.git.head(workspace)
        self.git.validate_branch_ref(workspace, branch_ref)
        try:
            self.git.add_worktree(workspace, target, branch_ref, base_commit)
            self.initialize_path(workspace, target)
            gitdir = read_gitdir_pointer(target)
        except (WorktreeError, TeamError) as exc:
            cleanup_failed = False
            if target.exists():
                try:
                    self.git.remove_worktree(workspace, target)
                except WorktreeError:
                    cleanup_failed = True
            if self.git.ref_exists(workspace, branch_ref):
                try:
                    self.git.delete_ref(workspace, branch_ref, self.git.ref_tip(workspace, branch_ref))
                except WorktreeError:
                    cleanup_failed = True
            if cleanup_failed:
                raise TeamError(
                    "worktree_cleanup_failed",
                    "成员 Worktree 创建失败且补偿清理未完成；资源已保留并需要人工检查。",
                ) from exc
            if isinstance(exc, TeamError):
                raise
            raise TeamError(exc.code, exc.user_message) from exc
        now = utc_now()
        return TeamWorktreeIdentity(
            1, repository_id, team_name, member_id, managed_name, str(workspace),
            str(target), branch_ref, base_commit, base_commit, str(gitdir),
            initialization_fingerprint, "active", now, now,
        )

    def recover(self, identity: TeamWorktreeIdentity) -> TeamWorktreeIdentity:
        workspace = Path(identity.main_workspace).resolve(strict=True)
        target = Path(identity.worktree_path)
        if filesystem_repository_id(workspace) != identity.repository_id:
            raise TeamError("repository_mismatch", "成员 Worktree 仓库身份不匹配。")
        expected = workspace / ".mycode" / "worktrees" / identity.managed_name
        if target.resolve(strict=True) != expected.resolve(strict=True):
            raise TeamError("worktree_path_mismatch", "成员 Worktree 路径与持久化身份不一致。")
        registration = self.git.registration_for(workspace, target)
        if registration is None or registration.branch_ref != identity.branch_ref:
            raise TeamError("worktree_registration_mismatch", "Git Worktree 注册与成员身份不一致。")
        if str(read_gitdir_pointer(target)) != identity.expected_gitdir:
            raise TeamError("worktree_gitdir_mismatch", "成员 Worktree gitdir 与身份不一致。")
        self.verify_initialization(workspace, target)
        return replace(identity, lifecycle_state="active", last_active_at=utc_now())

    def initialize_path(self, workspace: Path, target: Path) -> None:
        created: list[Path] = []
        try:
            for rule in self.config.initialization:
                source = self._safe_relative(workspace, rule.source)
                if not source.exists():
                    if rule.required:
                        raise TeamError("required_source_missing", f"Worktree 初始化必需源不存在：{rule.source}")
                    continue
                if rule.action == "hooks":
                    if not source.is_dir() or source.is_symlink():
                        raise TeamError("invalid_hooks_source", "Worktree hooks 初始化源无效。")
                    continue
                assert rule.target is not None
                destination = self._safe_relative(target, rule.target)
                if destination.exists() or destination.is_symlink():
                    if self._initialization_matches(rule.action, source, destination):
                        continue
                    raise TeamError("initialization_conflict", f"Worktree 初始化目标冲突：{rule.target}")
                if not self.git.check_ignored(target, rule.target):
                    raise TeamError("initialization_not_ignored", f"Worktree 初始化目标未被 Git ignore：{rule.target}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                created.append(destination)
                if rule.action == "symlink":
                    destination.symlink_to(source.resolve(strict=True), target_is_directory=source.is_dir())
                elif source.is_dir():
                    files = [item for item in source.rglob("*") if item.is_file()]
                    if len(files) > self.config.copy_max_files or sum(item.stat().st_size for item in files) > self.config.copy_max_bytes:
                        raise TeamError("initialization_copy_limit", "Worktree 初始化复制超过配置上限。")
                    shutil.copytree(source, destination, symlinks=False)
                else:
                    if source.stat().st_size > self.config.copy_max_bytes:
                        raise TeamError("initialization_copy_limit", "Worktree 初始化复制超过配置上限。")
                    shutil.copy2(source, destination, follow_symlinks=False)
        except Exception:
            for path in reversed(created):
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            raise

    def verify_initialization(self, workspace: Path, target: Path) -> None:
        for rule in self.config.initialization:
            source = self._safe_relative(workspace, rule.source)
            if not source.exists():
                if rule.required:
                    raise TeamError("recovery_source_missing", f"Worktree 初始化源已缺失：{rule.source}")
                continue
            if rule.action == "hooks":
                continue
            assert rule.target is not None
            destination = self._safe_relative(target, rule.target)
            if not self._initialization_matches(rule.action, source, destination):
                raise TeamError("recovery_initialization_mismatch", f"Worktree 初始化目标已变化：{rule.target}")

    @staticmethod
    def _safe_relative(root: Path, relative: str) -> Path:
        if Path(relative).is_absolute() or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise TeamError("unsafe_initialization_path", "Worktree 初始化路径不安全。")
        boundary = root.resolve(strict=True)
        candidate = root.joinpath(*relative.split("/"))
        cursor = candidate
        while not cursor.exists() and cursor != root:
            cursor = cursor.parent
        try:
            cursor.resolve(strict=True).relative_to(boundary)
        except (OSError, ValueError, RuntimeError) as exc:
            raise TeamError("initialization_path_escape", "Worktree 初始化路径逃离工作区。") from exc
        return candidate

    @staticmethod
    def _initialization_matches(action: str, source: Path, target: Path) -> bool:
        if action == "symlink":
            try:
                return target.is_symlink() and target.resolve(strict=True) == source.resolve(strict=True)
            except OSError:
                return False
        if source.is_file() and target.is_file() and not target.is_symlink():
            return source.read_bytes() == target.read_bytes()
        if source.is_dir() and target.is_dir() and not target.is_symlink():
            source_files = {item.relative_to(source) for item in source.rglob("*") if item.is_file()}
            target_files = {item.relative_to(target) for item in target.rglob("*") if item.is_file()}
            return source_files == target_files and all(
                (source / item).read_bytes() == (target / item).read_bytes()
                for item in source_files
            )
        return False

    def inspect(self, identity: TeamWorktreeIdentity) -> dict[str, object]:
        recovered = self.recover(identity)
        target = Path(recovered.worktree_path)
        head = self.git.head(target)
        clean = self.git.is_clean(target)
        commits = self.git.new_commits(target, recovered.integrated_commit, recovered.branch_ref)
        return {"clean": clean, "head": head, "unintegrated_commits": commits}

    def sync_baseline(self, identity: TeamWorktreeIdentity, integrated_commit: str) -> TeamWorktreeIdentity:
        target = Path(identity.worktree_path)
        if not self.git.is_ancestor(target, integrated_commit, identity.branch_ref):
            raise TeamError("integration_not_on_member_branch", "集成提交不属于成员分支。")
        return replace(identity, integrated_commit=integrated_commit, last_active_at=utc_now())

    def dispose(self, identity: TeamWorktreeIdentity) -> None:
        state = self.inspect(identity)
        if not state["clean"] or state["unintegrated_commits"]:
            raise TeamError("worktree_not_disposable", "成员 Worktree 含脏文件或未集成提交，拒绝清理。")
        workspace = Path(identity.main_workspace)
        target = Path(identity.worktree_path)
        tip = self.git.ref_tip(workspace, identity.branch_ref)
        try:
            self.git.unlock_worktree(workspace, target)
            self.git.remove_worktree(workspace, target)
            self.git.delete_ref(workspace, identity.branch_ref, tip)
        except WorktreeError as exc:
            raise TeamError(exc.code, exc.user_message) from exc
