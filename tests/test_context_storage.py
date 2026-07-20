from __future__ import annotations

from pathlib import Path

import pytest

from mycode.context.storage import ContextStorageError, ContextStore
from mycode.tools.files import ReadFileTool
from mycode.types import ToolContext


def test_writes_unique_utf8_files_with_workspace_relative_paths(tmp_path: Path) -> None:
    store = ContextStore(tmp_path, session_id="session-one")
    transaction = store.begin()

    first = transaction.write_tool_result("call/1", '{"text":"中文"}')
    second = transaction.write_tool_result("call/1", '{"text":"other"}')
    transaction.commit()

    assert first.path != second.path
    assert not Path(first.path).is_absolute()
    assert (tmp_path / first.path).read_text(encoding="utf-8") == '{"text":"中文"}'
    assert first.original_chars == len('{"text":"中文"}')


def test_stored_path_can_be_read_by_workspace_tool(tmp_path: Path) -> None:
    store = ContextStore(tmp_path, session_id="readable")
    transaction = store.begin()
    reference = transaction.write_user_message("message-1", "原始用户消息")
    transaction.commit()

    result = ReadFileTool().run(
        {"path": reference.path},
        ToolContext(workspace_root=tmp_path),
    )

    assert result.ok
    assert result.data["content"] == "原始用户消息"


def test_transaction_rollback_removes_new_files(tmp_path: Path) -> None:
    store = ContextStore(tmp_path, session_id="rollback")
    transaction = store.begin()
    reference = transaction.write_tool_result("call-1", "secret")

    transaction.rollback()

    assert not (tmp_path / reference.path).exists()


def test_transaction_rejects_writes_after_completion(tmp_path: Path) -> None:
    store = ContextStore(tmp_path, session_id="closed")
    transaction = store.begin()
    transaction.commit()

    with pytest.raises(ContextStorageError, match="已经结束"):
        transaction.write_user_message("1", "late")


def test_rejects_context_root_symlink_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-context-outside"
    outside.mkdir()
    (tmp_path / ".mycode").symlink_to(outside, target_is_directory=True)
    store = ContextStore(tmp_path, session_id="unsafe")

    with pytest.raises(ContextStorageError, match="工作区边界"):
        store.begin().write_tool_result("1", "secret")


def test_close_removes_only_current_session_directory(tmp_path: Path) -> None:
    first = ContextStore(tmp_path, session_id="first")
    first_transaction = first.begin()
    first_transaction.write_tool_result("1", "first")
    first_transaction.commit()
    second = ContextStore(tmp_path, session_id="second")
    second_transaction = second.begin()
    second_transaction.write_tool_result("2", "second")
    second_transaction.commit()

    assert first.close() is None

    assert not first.session_dir.exists()
    assert second.session_dir.exists()


def test_close_returns_safe_warning_on_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ContextStore(tmp_path, session_id="warning")
    transaction = store.begin()
    transaction.write_user_message("1", "sensitive-body")
    transaction.commit()

    def fail_cleanup(path: Path) -> None:
        raise PermissionError("sensitive-body")

    monkeypatch.setattr("mycode.context.storage.shutil.rmtree", fail_cleanup)

    warning = store.close()

    assert warning is not None
    assert "PermissionError" in warning
    assert "sensitive-body" not in warning
