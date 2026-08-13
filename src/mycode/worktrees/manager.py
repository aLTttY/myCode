from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from mycode.types import WorktreeConfig

from .git import GitRunner
from .identity import IdentityStore, SCHEMA_VERSION, read_gitdir_pointer
from .initializer import initialized_path_matches
from .locking import TargetLock
from .models import (
    InitializationResult,
    WorktreeDisposition,
    WorktreeError,
    WorktreeIdentity,
    WorktreeInspection,
    WorktreeLease,
    WorktreeRequest,
)
from .paths import (
    assert_managed_target,
    branch_ref_for_task,
    filesystem_repository_id,
    managed_name_for_task,
    record_path,
    validate_task_id,
    worktree_path,
)


class WorktreeRequestFactory:
    def __init__(
        self,
        git: GitRunner,
        identities: IdentityStore,
    ) -> None:
        self.git = git
        self.identities = identities

    def prepare(
        self,
        task_id: str,
        role_name: str,
        workspace: Path,
        initialization_fingerprint: str,
    ) -> WorktreeRequest:
        validate_task_id(task_id)
        main = workspace.resolve(strict=True)
        managed_name = managed_name_for_task(task_id)
        target = worktree_path(main, managed_name)
        branch_ref = branch_ref_for_task(task_id)
        now = datetime.now().astimezone()
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_dir():
                raise WorktreeError("target_conflict", "Worktree 目标已存在且不是受管目录。")
            identity = self.identities.recover(
                main,
                task_id,
                role_name,
                initialization_fingerprint,
            )
            return WorktreeRequest(
                task_id=task_id,
                role_name=role_name,
                managed_name=managed_name,
                main_workspace=main,
                repository_id=identity.repository_id,
                base_commit=identity.base_commit,
                base_ref=identity.base_ref,
                branch_ref=identity.branch_ref,
                worktree_path=identity.worktree_path,
                initialization_fingerprint=identity.initialization_fingerprint,
                created_at=identity.created_at,
                recovery_identity=identity,
            )
        if record_path(main, task_id).exists():
            raise WorktreeError("record_conflict", "Worktree 主身份记录已存在但目录缺失。")
        repository_id, base_commit, base_ref = self.git.capture_repository(main)
        managed_relative = target.relative_to(main).as_posix()
        if not self.git.check_ignored(main, managed_relative):
            raise WorktreeError(
                "managed_root_not_ignored",
                "仓库必须忽略固定 Worktree 目录 .mycode/worktrees/。",
            )
        if not self.git.check_ignored(main, ".mycode/worktree.json"):
            raise WorktreeError(
                "identity_marker_not_ignored",
                "仓库必须忽略 Worktree 身份标记 .mycode/worktree.json。",
            )
        self.git.validate_branch_ref(main, branch_ref)
        if self.git.ref_exists(main, branch_ref):
            raise WorktreeError("branch_conflict", "Worktree 临时分支已存在。")
        if self.git.registration_for(main, target) is not None:
            raise WorktreeError("registration_conflict", "Git 已注册同路径 Worktree。")
        return WorktreeRequest(
            task_id=task_id,
            role_name=role_name,
            managed_name=managed_name,
            main_workspace=main,
            repository_id=repository_id,
            base_commit=base_commit,
            base_ref=base_ref,
            branch_ref=branch_ref,
            worktree_path=target,
            initialization_fingerprint=initialization_fingerprint,
            created_at=now,
        )


class WorktreeManager:
    def __init__(
        self,
        config: WorktreeConfig,
        *,
        git: GitRunner | None = None,
        identities: IdentityStore | None = None,
    ) -> None:
        self.config = config
        self.git = git or GitRunner(config.git_timeout_seconds)
        self.identities = identities or IdentityStore()
        self.requests = WorktreeRequestFactory(self.git, self.identities)

    def enter(self, request: WorktreeRequest) -> WorktreeLease:
        target_lock = TargetLock(request.main_workspace, request.managed_name)
        if not target_lock.acquire(self.config.git_timeout_seconds):
            raise WorktreeError("lock_timeout", "取得 Worktree 目标锁超时。")
        created = False
        try:
            assert_managed_target(
                request.main_workspace,
                request.worktree_path,
                request.managed_name,
            )
            if request.recovery_identity is not None:
                identity = self.identities.validate_pair(request.recovery_identity)
                return WorktreeLease(
                    identity,
                    identity.worktree_path,
                    True,
                    target_lock,
                    MappingProxyType({}),
                )
            if request.worktree_path.exists() or record_path(request.main_workspace, request.task_id).exists():
                raise WorktreeError("create_conflict", "Worktree 创建目标或记录已存在。")
            if self.git.ref_exists(request.main_workspace, request.branch_ref):
                raise WorktreeError("branch_conflict", "Worktree 临时分支已存在。")
            self.git.add_worktree(
                request.main_workspace,
                request.worktree_path,
                request.branch_ref,
                request.base_commit,
            )
            created = True
            gitdir = read_gitdir_pointer(request.worktree_path)
            now = datetime.now().astimezone()
            identity = WorktreeIdentity(
                schema_version=SCHEMA_VERSION,
                repository_id=request.repository_id,
                task_id=request.task_id,
                role_name=request.role_name,
                managed_name=request.managed_name,
                main_workspace=request.main_workspace,
                worktree_path=request.worktree_path,
                branch_ref=request.branch_ref,
                base_commit=request.base_commit,
                base_ref=request.base_ref,
                expected_gitdir=gitdir,
                initialization_fingerprint=request.initialization_fingerprint,
                initialization_manifest=(),
                lifecycle_state="creating",
                created_at=request.created_at,
                last_active_at=now,
            )
            self.identities.write(identity)
            return WorktreeLease(
                identity,
                request.worktree_path,
                False,
                target_lock,
                MappingProxyType({}),
            )
        except Exception:
            if created:
                self._rollback_created(request)
            target_lock.release()
            raise

    def activate(
        self,
        lease: WorktreeLease,
        initialization: InitializationResult,
    ) -> WorktreeLease:
        identity = self.identities.transition(
            lease.identity,
            "active",
            manifest=initialization.manifest,
        )
        return replace(
            lease,
            identity=identity,
            process_environment=initialization.process_environment,
            initialization_diagnostics=initialization.diagnostics,
        )

    def abort_initialization(self, lease: WorktreeLease) -> WorktreeDisposition:
        identity = lease.identity
        try:
            # A recovered directory may contain ignored initialization files that
            # failed verification because an agent or user changed them.  Never
            # treat that situation as a disposable, freshly-created workspace.
            if lease.recovered:
                failed = self._transition_failure(identity)
                return WorktreeDisposition(
                    "cleanup_failed",
                    failed,
                    None,
                    "已有工作区初始化核验失败，已保留以防数据丢失。",
                )
            tracked, untracked = self.git.status(
                identity.worktree_path,
                lease.process_environment,
            )
            ignored = tuple(
                path
                for path in self.git.ignored_untracked(
                    identity.worktree_path,
                    lease.process_environment,
                )
                if path != ".mycode/worktree.json"
            )
            tip = self.git.ref_tip(identity.main_workspace, identity.branch_ref)
            if tracked or untracked or ignored or tip != identity.base_commit:
                failed = self._transition_failure(identity)
                return WorktreeDisposition(
                    "cleanup_failed",
                    failed,
                    None,
                    "初始化失败后检测到无法安全回滚的状态，已保留。",
                )
            disposition = self._remove_locked(identity, None)
            return disposition
        except Exception:
            failed = self._transition_failure(identity)
            return WorktreeDisposition(
                "cleanup_failed",
                failed,
                None,
                "初始化回滚检查失败，已保留。",
            )
        finally:
            lease.lock_token.release()

    def inspect(
        self,
        identity: WorktreeIdentity,
        environment: dict[str, str] | MappingProxyType | None = None,
    ) -> WorktreeInspection:
        self.identities.validate_pair(identity)
        registration = self.git.registration_for(identity.main_workspace, identity.worktree_path)
        if registration is None or registration.branch_ref != identity.branch_ref:
            raise WorktreeError("registration_mismatch", "Git Worktree 注册与身份不匹配。")
        tracked, untracked = self.git.status(identity.worktree_path, environment)
        managed_targets: list[str] = []
        for item in identity.initialization_manifest:
            if item.action == "hooks":
                continue
            if not initialized_path_matches(identity, item):
                untracked = True
                continue
            if item.target is not None:
                managed_targets.append(item.target.rstrip("/"))
        for ignored_path in self.git.ignored_untracked(
            identity.worktree_path,
            environment,
        ):
            if ignored_path == ".mycode/worktree.json":
                continue
            if any(
                ignored_path == target or ignored_path.startswith(target + "/")
                for target in managed_targets
            ):
                continue
            untracked = True
            break
        commits = self.git.new_commits(
            identity.main_workspace,
            identity.base_commit,
            identity.branch_ref,
        )
        delivery_refs = self.git.delivery_refs(
            identity.main_workspace,
            identity.task_id,
            identity.branch_ref,
        )
        protected: list[str] = []
        for commit in commits:
            delivered = self.git.is_ancestor(identity.main_workspace, commit, identity.base_ref)
            if not delivered:
                delivered = any(
                    self.git.is_ancestor(identity.main_workspace, commit, ref)
                    for ref in delivery_refs
                )
            if not delivered:
                protected.append(commit)
        has_changes = tracked or untracked
        if has_changes:
            reason = "uncommitted_changes"
        elif protected:
            reason = "unmerged_unpushed_commits"
        else:
            reason = "none"
        return WorktreeInspection(
            has_tracked_changes=tracked,
            has_untracked_changes=untracked,
            new_commits=commits,
            primary_ref=identity.base_ref,
            delivery_refs=delivery_refs,
            protected_commits=tuple(protected),
            safe_for_task_exit=not has_changes and not commits,
            safe_for_protected_delete=not has_changes and not protected,
            retention_reason=reason,
        )

    def exit(self, lease: WorktreeLease) -> WorktreeDisposition:
        identity = lease.identity
        try:
            inspection = self.inspect(identity, lease.process_environment)
            if inspection.safe_for_task_exit:
                return self._remove_locked(identity, inspection)
            state = self.identities.transition(identity, "retained")
            if inspection.has_tracked_changes or inspection.has_untracked_changes:
                return WorktreeDisposition(
                    "retained_changes",
                    state,
                    inspection,
                    "存在未提交修改，工作区已保留。",
                )
            return WorktreeDisposition(
                "retained_commits",
                state,
                inspection,
                "存在新增提交，工作区已保留。",
            )
        except Exception:
            failed = self._transition_failure(identity)
            return WorktreeDisposition(
                "cleanup_failed",
                failed,
                None,
                "退出状态检查失败，工作区已保留。",
            )
        finally:
            lease.lock_token.release()

    def delete(
        self,
        identity: WorktreeIdentity,
        *,
        lock_timeout_seconds: float | None = None,
    ) -> WorktreeDisposition:
        try:
            self.identities.validate_pair(
                identity,
                allowed_states=("creating", "active", "retained", "cleanup_failed"),
            )
        except Exception:
            return WorktreeDisposition(
                "cleanup_failed",
                identity,
                None,
                "Worktree 身份或路径预检失败，未执行删除。",
            )
        target_lock = TargetLock(identity.main_workspace, identity.managed_name)
        timeout = (
            self.config.git_timeout_seconds
            if lock_timeout_seconds is None
            else lock_timeout_seconds
        )
        if not target_lock.acquire(timeout):
            return WorktreeDisposition(
                "cleanup_failed", identity, None, "Worktree 正在使用，未执行删除。"
            )
        try:
            inspection = self.inspect(identity)
            if not inspection.safe_for_protected_delete:
                state = self.identities.transition(identity, "retained")
                status = (
                    "retained_changes"
                    if inspection.has_tracked_changes or inspection.has_untracked_changes
                    else "retained_commits"
                )
                return WorktreeDisposition(status, state, inspection, "保护条件未满足，工作区已保留。")
            return self._remove_locked(identity, inspection)
        except Exception:
            failed = self._transition_failure(identity)
            return WorktreeDisposition(
                "cleanup_failed", failed, None, "保护性删除检查失败，工作区已保留。"
            )
        finally:
            target_lock.release()

    def managed_candidates(self, main_workspace: Path) -> tuple[WorktreeIdentity, ...]:
        return self.identities.candidates(main_workspace.resolve(strict=True))

    def managed_candidate_scan(self, main_workspace: Path):
        return self.identities.candidate_scan(main_workspace.resolve(strict=True))

    def _remove_locked(
        self,
        identity: WorktreeIdentity,
        inspection: WorktreeInspection | None,
    ) -> WorktreeDisposition:
        self.identities.validate_pair(
            identity,
            allowed_states=("creating", "active", "retained", "cleanup_failed"),
        )
        expected_tip = self.git.ref_tip(identity.main_workspace, identity.branch_ref)
        self.git.unlock_worktree(identity.main_workspace, identity.worktree_path)
        self.git.remove_worktree(identity.main_workspace, identity.worktree_path)
        ref_failure = False
        try:
            self.git.delete_ref(identity.main_workspace, identity.branch_ref, expected_tip)
        except Exception:
            ref_failure = True
        try:
            self.identities.remove_primary(identity)
        except Exception:
            return WorktreeDisposition(
                "cleanup_failed",
                identity,
                inspection,
                "Worktree 和分支已删除，但身份记录清理失败。",
            )
        if ref_failure:
            return WorktreeDisposition(
                "cleanup_failed",
                identity,
                inspection,
                "Worktree 已删除，但临时分支并发变化或删除失败，分支已保留。",
            )
        return WorktreeDisposition("cleaned", identity, inspection, "工作区已安全清理。")

    def _rollback_created(self, request: WorktreeRequest) -> None:
        try:
            self.git.unlock_worktree(request.main_workspace, request.worktree_path)
        except Exception:
            pass
        try:
            self.git.remove_worktree(request.main_workspace, request.worktree_path)
        except Exception:
            return
        try:
            if self.git.ref_exists(request.main_workspace, request.branch_ref):
                tip = self.git.ref_tip(request.main_workspace, request.branch_ref)
                if tip == request.base_commit:
                    self.git.delete_ref(request.main_workspace, request.branch_ref, tip)
        except Exception:
            pass
        try:
            record_path(request.main_workspace, request.task_id).unlink(missing_ok=True)
        except OSError:
            pass

    def _transition_failure(self, identity: WorktreeIdentity) -> WorktreeIdentity:
        try:
            self.identities.validate_pair(
                identity,
                allowed_states=("creating", "active", "retained", "cleanup_failed"),
            )
            return self.identities.transition(identity, "cleanup_failed")
        except Exception:
            pass
        return identity
