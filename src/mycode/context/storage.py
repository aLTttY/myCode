from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from .estimator import approximate_tokens
from .models import StoredContextReference


SAFE_SOURCE = re.compile(r"[^A-Za-z0-9_-]+")


class ContextStorageError(Exception):
    pass


class ContextStore:
    def __init__(self, workspace_root: Path, session_id: str | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.session_id = session_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.session_id):
            raise ContextStorageError("上下文会话标识非法。")
        self._session_dir: Path | None = None

    @property
    def session_dir(self) -> Path:
        if self._session_dir is not None:
            return self._session_dir
        return self.workspace_root / ".mycode" / "context" / self.session_id

    def begin(self) -> ContextTransaction:
        return ContextTransaction(self)

    def close(self) -> str | None:
        session_dir = self._session_dir
        if session_dir is None or not session_dir.exists():
            return None
        try:
            shutil.rmtree(session_dir)
        except OSError as exc:
            return f"上下文会话目录清理失败（{type(exc).__name__}）。"
        self._session_dir = None
        return None

    def _ensure_session_dir(self) -> Path:
        context_root = (self.workspace_root / ".mycode" / "context").resolve()
        self._require_inside_workspace(context_root)
        session_dir = context_root / self.session_id
        if session_dir.is_symlink():
            raise ContextStorageError("上下文会话目录不能是符号链接。")
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ContextStorageError(
                f"无法创建上下文会话目录（{type(exc).__name__}）。"
            ) from exc
        resolved = session_dir.resolve()
        self._require_inside_workspace(resolved)
        if not resolved.is_dir():
            raise ContextStorageError("上下文会话路径不是目录。")
        self._session_dir = resolved
        return resolved

    def _require_inside_workspace(self, path: Path) -> None:
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ContextStorageError("上下文路径越过工作区边界。") from exc


class ContextTransaction:
    def __init__(self, store: ContextStore) -> None:
        self.store = store
        self._created: list[Path] = []
        self._closed = False

    def write_tool_result(self, source_id: str, content: str) -> StoredContextReference:
        return self._write("tool_result", source_id, content, ".json")

    def write_user_message(self, source_id: str, content: str) -> StoredContextReference:
        return self._write("user_message", source_id, content, ".txt")

    def commit(self) -> None:
        self._ensure_open()
        self._closed = True

    def rollback(self) -> None:
        if self._closed:
            return
        for path in reversed(self._created):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._closed = True

    def _write(
        self,
        kind: str,
        source_id: str,
        content: str,
        suffix: str,
    ) -> StoredContextReference:
        self._ensure_open()
        if not isinstance(content, str):
            raise ContextStorageError("上下文文件内容必须是字符串。")
        session_dir = self.store._ensure_session_dir()
        safe_source = SAFE_SOURCE.sub("-", source_id).strip("-")[:40] or "item"
        filename = f"{kind}-{safe_source}-{uuid.uuid4().hex}{suffix}"
        final_path = session_dir / filename
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{filename}.",
                suffix=".tmp",
                dir=session_dir,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, final_path)
        except OSError as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ContextStorageError(
                f"上下文文件写入失败（{type(exc).__name__}）。"
            ) from exc
        self._created.append(final_path)
        relative = final_path.relative_to(self.store.workspace_root).as_posix()
        return StoredContextReference(
            path=relative,
            kind="tool_result" if kind == "tool_result" else "user_message",
            original_chars=len(content),
            approximate_tokens=approximate_tokens(content),
            source_id=source_id,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise ContextStorageError("上下文存储事务已经结束。")
