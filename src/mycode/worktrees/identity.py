from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from mycode.types import WorktreeInitRule

from .models import InitializedPath, WorktreeDiagnostic, WorktreeError, WorktreeIdentity
from .paths import (
    assert_managed_target,
    branch_ref_for_task,
    common_git_directory,
    filesystem_repository_id,
    managed_name_for_task,
    marker_path,
    record_path,
    validate_managed_name,
    validate_task_id,
)


SCHEMA_VERSION = 1
_FIELDS = {
    "schema_version",
    "repository_id",
    "task_id",
    "role_name",
    "managed_name",
    "main_workspace",
    "worktree_path",
    "branch_ref",
    "base_commit",
    "base_ref",
    "expected_gitdir",
    "initialization_fingerprint",
    "initialization_manifest",
    "lifecycle_state",
    "created_at",
    "last_active_at",
}
_MANIFEST_FIELDS = {"action", "source", "target", "required"}


def initialization_fingerprint(rules: tuple[WorktreeInitRule, ...]) -> str:
    value = [
        {
            "action": rule.action,
            "source": rule.source,
            "target": rule.target,
            "required": rule.required,
        }
        for rule in rules
    ]
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class IdentityStore:
    def write(self, identity: WorktreeIdentity) -> None:
        payload = _serialize(identity)
        _atomic_json(record_path(identity.main_workspace, identity.task_id), payload)
        _atomic_json(marker_path(identity.worktree_path), payload)

    def transition(
        self,
        identity: WorktreeIdentity,
        state: str,
        *,
        manifest: tuple[InitializedPath, ...] | None = None,
        last_active_at: datetime | None = None,
    ) -> WorktreeIdentity:
        if state not in {"creating", "active", "retained", "cleanup_failed"}:
            raise WorktreeError("invalid_state", "Worktree 生命周期状态无效。")
        updated = replace(
            identity,
            lifecycle_state=state,
            initialization_manifest=(
                identity.initialization_manifest if manifest is None else manifest
            ),
            last_active_at=last_active_at or datetime.now().astimezone(),
        )
        self.write(updated)
        return updated

    def read_primary(self, main_workspace: Path, task_id: str) -> WorktreeIdentity:
        return _read_identity(record_path(main_workspace, task_id))

    def read_marker(self, target: Path) -> WorktreeIdentity:
        return _read_identity(marker_path(target))

    def validate_pair(
        self,
        identity: WorktreeIdentity,
        *,
        allowed_states: tuple[str, ...] = ("active", "retained", "cleanup_failed"),
    ) -> WorktreeIdentity:
        validate_task_id(identity.task_id)
        validate_managed_name(identity.managed_name)
        assert_managed_target(identity.main_workspace, identity.worktree_path, identity.managed_name)
        if filesystem_repository_id(identity.main_workspace) != identity.repository_id:
            raise WorktreeError("repository_mismatch", "Worktree 仓库身份不匹配。")
        primary = self.read_primary(identity.main_workspace, identity.task_id)
        marker = self.read_marker(identity.worktree_path)
        if primary != marker or primary != identity:
            raise WorktreeError("identity_mismatch", "Worktree 双身份记录不匹配。")
        if identity.lifecycle_state not in allowed_states:
            raise WorktreeError("identity_state", "Worktree 身份状态不允许恢复或清理。")
        gitdir = read_gitdir_pointer(identity.worktree_path)
        if gitdir != identity.expected_gitdir.resolve(strict=False):
            raise WorktreeError("gitdir_mismatch", "Worktree .git 指针与身份记录不匹配。")
        try:
            gitdir.relative_to(common_git_directory(identity.main_workspace) / "worktrees")
        except ValueError as exc:
            raise WorktreeError(
                "gitdir_escape",
                "Worktree gitdir 不属于当前仓库的受管 Git 目录。",
            ) from exc
        return identity

    def recover(
        self,
        main_workspace: Path,
        task_id: str,
        role_name: str,
        fingerprint: str,
    ) -> WorktreeIdentity:
        identity = self.read_primary(main_workspace, task_id)
        if identity.role_name != role_name:
            raise WorktreeError("role_mismatch", "Worktree 角色身份不匹配。")
        if identity.initialization_fingerprint != fingerprint:
            raise WorktreeError("initialization_changed", "Worktree 初始化配置已变化，拒绝快速恢复。")
        return self.validate_pair(identity)

    def remove_primary(self, identity: WorktreeIdentity) -> None:
        path = record_path(identity.main_workspace, identity.task_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise WorktreeError("record_remove_failed", "Worktree 主身份记录删除失败。") from exc

    def candidates(self, main_workspace: Path) -> tuple[WorktreeIdentity, ...]:
        return self.candidate_scan(main_workspace)[0]

    def candidate_scan(
        self,
        main_workspace: Path,
    ) -> tuple[tuple[WorktreeIdentity, ...], tuple[WorktreeDiagnostic, ...]]:
        expected_workspace = main_workspace.resolve(strict=True)
        root = record_path(main_workspace, "agt_0000000000000000").parent
        try:
            paths = tuple(sorted(root.glob("agt_*.json")))
        except OSError:
            return (), (
                WorktreeDiagnostic("error", "record_scan_failed", None, "无法读取 Worktree 主身份记录目录。"),
            )
        identities: list[WorktreeIdentity] = []
        diagnostics: list[WorktreeDiagnostic] = []
        for path in paths:
            try:
                identity = _read_identity(path)
                if record_path(main_workspace, identity.task_id) != path:
                    diagnostics.append(
                        WorktreeDiagnostic("warning", "record_name_mismatch", None, f"身份记录 {path.name} 的任务名称不匹配，已跳过。")
                    )
                    continue
                if identity.main_workspace != expected_workspace:
                    diagnostics.append(
                        WorktreeDiagnostic(
                            "warning",
                            "record_repository_mismatch",
                            None,
                            f"身份记录 {path.name} 不属于当前仓库，已跳过。",
                        )
                    )
                    continue
                identities.append(identity)
            except (OSError, WorktreeError):
                diagnostics.append(
                    WorktreeDiagnostic("warning", "record_corrupt", None, f"身份记录 {path.name} 无法严格解析，已跳过。")
                )
                continue
        return tuple(identities), tuple(diagnostics)


def read_gitdir_pointer(target: Path) -> Path:
    pointer = target / ".git"
    try:
        if pointer.is_symlink() or not pointer.is_file():
            raise WorktreeError("invalid_gitdir", "Worktree .git 必须是普通指针文件。")
        text = pointer.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise WorktreeError("invalid_gitdir", "无法读取 Worktree .git 指针。") from exc
    if not text.startswith("gitdir: ") or "\n" in text or "\r" in text:
        raise WorktreeError("invalid_gitdir", "Worktree .git 指针格式无效。")
    raw = Path(text[8:])
    try:
        return (target / raw).resolve(strict=True) if not raw.is_absolute() else raw.resolve(strict=True)
    except OSError as exc:
        raise WorktreeError("invalid_gitdir", "Worktree gitdir 不存在。") from exc


def _serialize(identity: WorktreeIdentity) -> dict[str, object]:
    return {
        "schema_version": identity.schema_version,
        "repository_id": identity.repository_id,
        "task_id": identity.task_id,
        "role_name": identity.role_name,
        "managed_name": identity.managed_name,
        "main_workspace": str(identity.main_workspace),
        "worktree_path": str(identity.worktree_path),
        "branch_ref": identity.branch_ref,
        "base_commit": identity.base_commit,
        "base_ref": identity.base_ref,
        "expected_gitdir": str(identity.expected_gitdir),
        "initialization_fingerprint": identity.initialization_fingerprint,
        "initialization_manifest": [
            {
                "action": item.action,
                "source": item.source,
                "target": item.target,
                "required": item.required,
            }
            for item in identity.initialization_manifest
        ],
        "lifecycle_state": identity.lifecycle_state,
        "created_at": identity.created_at.isoformat(),
        "last_active_at": identity.last_active_at.isoformat(),
    }


def _read_identity(path: Path) -> WorktreeIdentity:
    try:
        if path.is_symlink() or not path.is_file():
            raise WorktreeError("identity_missing", "Worktree 身份记录不存在。")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except WorktreeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorktreeError("identity_corrupt", "Worktree 身份记录损坏。") from exc
    if not isinstance(raw, dict) or set(raw) != _FIELDS:
        raise WorktreeError("identity_schema", "Worktree 身份记录 schema 无效。")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise WorktreeError("identity_version", "Worktree 身份记录版本不受支持。")
    required_strings = (
        "repository_id",
        "task_id",
        "role_name",
        "managed_name",
        "main_workspace",
        "worktree_path",
        "branch_ref",
        "base_commit",
        "base_ref",
        "expected_gitdir",
        "initialization_fingerprint",
        "lifecycle_state",
        "created_at",
        "last_active_at",
    )
    if any(not isinstance(raw.get(key), str) or not raw[key] for key in required_strings):
        raise WorktreeError("identity_schema", "Worktree 身份记录字段类型无效。")
    state = raw["lifecycle_state"]
    if state not in {"creating", "active", "retained", "cleanup_failed"}:
        raise WorktreeError("identity_state", "Worktree 身份状态无效。")
    manifest_raw = raw.get("initialization_manifest")
    if not isinstance(manifest_raw, list):
        raise WorktreeError("identity_schema", "Worktree 初始化清单无效。")
    manifest: list[InitializedPath] = []
    for item in manifest_raw:
        if not isinstance(item, dict) or set(item) != _MANIFEST_FIELDS:
            raise WorktreeError("identity_schema", "Worktree 初始化清单项无效。")
        action = item.get("action")
        source = item.get("source")
        target = item.get("target")
        required = item.get("required")
        if (
            action not in {"copy", "symlink", "hooks"}
            or not isinstance(source, str)
            or not source
            or (action == "hooks" and target is not None)
            or (
                action != "hooks"
                and (not isinstance(target, str) or not target)
            )
            or not isinstance(required, bool)
        ):
            raise WorktreeError("identity_schema", "Worktree 初始化清单项字段无效。")
        _validate_manifest_path(source)
        if target is not None:
            _validate_manifest_path(target)
        manifest.append(InitializedPath(action, source, target, required))
    try:
        created_at = datetime.fromisoformat(raw["created_at"])
        last_active_at = datetime.fromisoformat(raw["last_active_at"])
        main_workspace = Path(raw["main_workspace"])
        target = Path(raw["worktree_path"])
        expected_gitdir = Path(raw["expected_gitdir"])
    except (TypeError, ValueError) as exc:
        raise WorktreeError("identity_schema", "Worktree 身份时间或路径无效。") from exc
    if (
        created_at.tzinfo is None
        or last_active_at.tzinfo is None
        or not main_workspace.is_absolute()
        or not target.is_absolute()
        or not expected_gitdir.is_absolute()
    ):
        raise WorktreeError("identity_schema", "Worktree 身份时间或路径必须是绝对值。")
    validate_task_id(raw["task_id"])
    validate_managed_name(raw["managed_name"])
    if raw["managed_name"] != managed_name_for_task(raw["task_id"]):
        raise WorktreeError("identity_schema", "Worktree 受管名称与任务身份不匹配。")
    if raw["branch_ref"] != branch_ref_for_task(raw["task_id"]):
        raise WorktreeError("identity_schema", "Worktree 分支与任务身份不匹配。")
    if any(
        len(raw[field]) != length
        or any(character not in "0123456789abcdef" for character in raw[field])
        for field, length in (
            ("repository_id", 64),
            ("base_commit", 40),
            ("initialization_fingerprint", 64),
        )
    ):
        raise WorktreeError("identity_schema", "Worktree 身份摘要格式无效。")
    if not raw["base_ref"].startswith("refs/heads/"):
        raise WorktreeError("identity_schema", "Worktree 基线引用格式无效。")
    return WorktreeIdentity(
        schema_version=SCHEMA_VERSION,
        repository_id=raw["repository_id"],
        task_id=raw["task_id"],
        role_name=raw["role_name"],
        managed_name=raw["managed_name"],
        main_workspace=main_workspace,
        worktree_path=target,
        branch_ref=raw["branch_ref"],
        base_commit=raw["base_commit"],
        base_ref=raw["base_ref"],
        expected_gitdir=expected_gitdir,
        initialization_fingerprint=raw["initialization_fingerprint"],
        initialization_manifest=tuple(manifest),
        lifecycle_state=state,
        created_at=created_at,
        last_active_at=last_active_at,
    )


def _validate_manifest_path(value: str) -> None:
    parts = value.split("/")
    if (
        "\\" in value
        or Path(value).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or parts[:2] == [".mycode", "worktrees"]
    ):
        raise WorktreeError("identity_schema", "Worktree 初始化清单路径无效。")


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise WorktreeError("identity_write_failed", "Worktree 身份记录写入失败。") from exc
