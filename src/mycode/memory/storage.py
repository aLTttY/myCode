from __future__ import annotations

import os
import re
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

from .models import MemoryIndexEntry, MemoryNote, MemoryOperation, MemoryScope
from .parser import MemoryFormatError, NOTE_ID_RE, parse_note, render_note
from .secrets import find_secret


INDEX_MAX_LINES = 200
INDEX_MAX_BYTES = 25 * 1024
INDEX_WARN_LINES = 180
INDEX_WARN_BYTES = 22 * 1024
CATEGORY_ORDER = ("user_preference", "correction_feedback", "project_knowledge", "reference")
INDEX_ID_RE = re.compile(r"^- \[(\d{8}-\d{6}-[0-9a-f]{4})\]\(")


class MemoryStorageError(Exception):
    pass


class MemoryStore:
    def __init__(self, workspace_root: Path, user_root: Path | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.user_root = (user_root or (Path.home() / ".mycode")).resolve()

    def root_for(self, scope: MemoryScope) -> Path:
        return self.workspace_root / ".mycode" / "memory" if scope == "project" else self.user_root / "memory"

    def list_notes(self, scope: MemoryScope) -> tuple[MemoryNote, ...]:
        root = self.root_for(scope)
        if not root.is_dir() or root.is_symlink():
            return ()
        notes: list[MemoryNote] = []
        for path in sorted(root.glob("*.md")):
            if path.name == "index.md" or path.is_symlink():
                continue
            try:
                note = parse_note(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, MemoryFormatError):
                continue
            if note.scope == scope and path.stem == note.id:
                notes.append(note)
        return tuple(notes)

    def known_ids(self) -> dict[str, set[str]]:
        return {scope: {note.id for note in self.list_notes(scope)} for scope in ("project", "user")}

    def read_note(self, scope: MemoryScope, note_id: str) -> MemoryNote:
        if not NOTE_ID_RE.fullmatch(note_id):
            raise MemoryStorageError("笔记 ID 非法。")
        path = self.root_for(scope) / f"{note_id}.md"
        if path.is_symlink():
            raise MemoryStorageError("笔记不能是符号链接。")
        try:
            note = parse_note(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, MemoryFormatError) as exc:
            raise MemoryStorageError("目标笔记不存在或损坏。") from exc
        if note.scope != scope or note.id != note_id:
            raise MemoryStorageError("目标笔记作用域不匹配。")
        return note

    def read_index(self, scope: MemoryScope) -> str:
        path = self.root_for(scope) / "index.md"
        if path.is_symlink():
            return ""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""
        if len(text.splitlines()) > INDEX_MAX_LINES or len(text.encode("utf-8")) > INDEX_MAX_BYTES:
            return ""
        return text

    def create(self, operation: MemoryOperation, source_session: str, now: datetime | None = None) -> MemoryNote:
        current = now or datetime.now().astimezone()
        note_id = f"{current:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        while (self.root_for(operation.scope) / f"{note_id}.md").exists():
            note_id = f"{current:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        note = MemoryNote(
            id=note_id,
            category=operation.category,
            scope=operation.scope,
            importance=operation.importance,
            created_at=current,
            updated_at=current,
            source_session=source_session,
            title=operation.title,
            summary=operation.summary,
            body=operation.body,
        )
        self._write_note(note)
        self.rebuild_index(operation.scope)
        return note

    def update(self, operation: MemoryOperation, source_session: str, now: datetime | None = None) -> MemoryNote:
        previous = self.read_note(operation.scope, operation.target_id)
        if previous.category != operation.category:
            raise MemoryStorageError("更新不能改变笔记分类。")
        note = MemoryNote(
            id=previous.id,
            category=previous.category,
            scope=previous.scope,
            importance=operation.importance,
            created_at=previous.created_at,
            updated_at=now or datetime.now().astimezone(),
            source_session=source_session,
            title=operation.title,
            summary=operation.summary,
            body=operation.body,
        )
        self._write_note(note)
        self.rebuild_index(operation.scope)
        return note

    def rebuild_index(self, scope: MemoryScope) -> str:
        entries = [
            MemoryIndexEntry(note.id, f"{note.id}.md", note.category, note.importance, note.updated_at, note.title, note.summary)
            for note in self.list_notes(scope)
        ]
        text = self._bounded_index(scope, entries)
        if find_secret(text):
            raise MemoryStorageError("索引候选命中敏感内容规则。")
        self._atomic_write(self.root_for(scope) / "index.md", text)
        return text

    def needs_compaction(self, scope: MemoryScope) -> bool:
        text = self.read_index(scope)
        return len(text.splitlines()) >= INDEX_WARN_LINES or len(text.encode("utf-8")) >= INDEX_WARN_BYTES

    def write_compacted_index(self, scope: MemoryScope, updates: dict[str, tuple[str, int]]) -> str:
        notes = self.list_notes(scope)
        if set(updates) != {note.id for note in notes}:
            raise MemoryStorageError("精简索引 ID 集合不匹配。")
        entries = [
            MemoryIndexEntry(
                note.id,
                f"{note.id}.md",
                note.category,
                updates[note.id][1],
                note.updated_at,
                note.title,
                updates[note.id][0],
            )
            for note in notes
        ]
        text = self._bounded_index(scope, entries)
        if find_secret(text):
            raise MemoryStorageError("精简索引命中敏感内容规则。")
        self._atomic_write(self.root_for(scope) / "index.md", text)
        return text

    def reconcile(self, scope: MemoryScope) -> str:
        root = self.root_for(scope)
        if not root.exists():
            return ""
        notes = self.list_notes(scope)
        existing = self.read_index(scope)
        indexed = [match.group(1) for line in existing.splitlines() if (match := INDEX_ID_RE.match(line))]
        note_ids = {note.id for note in notes}
        if existing and len(indexed) == len(set(indexed)) and set(indexed).issubset(note_ids):
            # A compacted index may intentionally omit low-value notes.
            missing = note_ids - set(indexed)
            try:
                index_mtime = (root / "index.md").stat().st_mtime_ns
                has_new_orphan = any((root / f"{note_id}.md").stat().st_mtime_ns > index_mtime for note_id in missing)
            except OSError:
                has_new_orphan = True
            if not has_new_orphan:
                return existing
        return self.rebuild_index(scope)

    def _write_note(self, note: MemoryNote) -> None:
        text = render_note(note)
        code = find_secret(text)
        if code:
            raise MemoryStorageError(f"笔记候选命中敏感内容规则：{code}。")
        self._atomic_write(self.root_for(note.scope) / f"{note.id}.md", text)

    def _atomic_write(self, path: Path, content: str) -> None:
        root = path.parent
        temporary: Path | None = None
        if root.is_symlink():
            raise MemoryStorageError("记忆目录不能是符号链接。")
        try:
            root.mkdir(parents=True, exist_ok=True)
            boundary = self.workspace_root if root == self.workspace_root / ".mycode" / "memory" else self.user_root
            root.resolve().relative_to(boundary.resolve())
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=root)
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError) as exc:
            try:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise MemoryStorageError(f"记忆文件写入失败（{type(exc).__name__}）。") from exc

    @staticmethod
    def _bounded_index(scope: MemoryScope, entries: list[MemoryIndexEntry]) -> str:
        ordered = sorted(entries, key=lambda item: (-item.importance, -item.updated_at.timestamp(), item.note_id))

        def render(items: list[MemoryIndexEntry]) -> str:
            lines = [f"# {scope.title()} Memory Index", "", "条目按价值和更新时间排列；项目级记忆优先于用户级记忆。"]
            for category in CATEGORY_ORDER:
                lines.extend(["", f"## {category}"])
                for entry in items:
                    if entry.category == category:
                        summary = " ".join(entry.summary.split())
                        title = " ".join(entry.title.split())
                        lines.append(
                            f"- [{entry.note_id}]({entry.filename}) | importance={entry.importance} | updated={entry.updated_at.isoformat()} | {title}: {summary}"
                        )
            return "\n".join(lines).rstrip() + "\n"

        while ordered:
            text = render(ordered)
            if len(text.splitlines()) <= INDEX_MAX_LINES and len(text.encode("utf-8")) <= INDEX_MAX_BYTES:
                return text
            ordered.pop()
        return render([])
