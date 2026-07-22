from datetime import datetime, timedelta
from pathlib import Path

import pytest

from mycode.memory.models import MemoryIndexEntry, MemoryOperation
from mycode.memory.storage import INDEX_MAX_BYTES, INDEX_MAX_LINES, MemoryStorageError, MemoryStore


def test_memory_store_separates_scopes_and_rebuilds_index(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, tmp_path / "home" / ".mycode")
    operation = MemoryOperation(
        action="create", scope="project", category="project_knowledge", importance=4,
        title="Stack", summary="Python project", body="Uses Python.",
    )
    note = store.create(operation, "20260721-100000-abcd")

    assert store.read_note("project", note.id).title == "Stack"
    assert note.id in store.read_index("project")
    assert store.read_index("user") == ""
    assert len(store.read_index("project").splitlines()) <= INDEX_MAX_LINES
    assert len(store.read_index("project").encode()) <= INDEX_MAX_BYTES


def test_reconcile_preserves_valid_compacted_index(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, tmp_path / "home" / ".mycode")
    operation = MemoryOperation(
        action="create", scope="project", category="project_knowledge", importance=4,
        title="Stack", summary="Long summary", body="Uses Python.",
    )
    note = store.create(operation, "20260721-100000-abcd")
    compacted = store.write_compacted_index("project", {note.id: ("Short", 5)})

    assert store.reconcile("project") == compacted
    assert "Short" in store.read_index("project")


def test_memory_store_rejects_secret_without_writing_note(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, tmp_path / "home" / ".mycode")
    operation = MemoryOperation(
        action="create", scope="project", category="reference", importance=5,
        title="Credential", summary="Do not keep", body="api_key=sk-abcdefghijklmnop",
    )

    with pytest.raises(MemoryStorageError, match="敏感内容规则"):
        store.create(operation, "20260721-100000-abcd")

    assert store.list_notes("project") == ()


def test_index_fallback_enforces_line_and_byte_limits_deterministically() -> None:
    now = datetime.now().astimezone()
    entries = [
        MemoryIndexEntry(
            note_id=f"20260721-{index // 60:02d}{index % 60:02d}00-{index:04x}"[-25:],
            filename=f"note-{index}.md",
            category="reference",
            importance=(index % 5) + 1,
            updated_at=now - timedelta(minutes=index),
            title=f"Title {index}",
            summary="中文摘要" * 200,
        )
        for index in range(220)
    ]

    first = MemoryStore._bounded_index("project", entries)
    second = MemoryStore._bounded_index("project", entries)

    assert first == second
    assert len(first.splitlines()) <= INDEX_MAX_LINES
    assert len(first.encode("utf-8")) <= INDEX_MAX_BYTES
