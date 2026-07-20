from pathlib import Path

from mycode.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from mycode.types import ToolContext


def context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, max_output_chars=100)


def test_read_file_reads_workspace_file(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")

    result = ReadFileTool().run({"path": "a.txt"}, context(tmp_path))

    assert result.ok is True
    assert result.data["content"] == "hello"


def test_read_file_preserves_complete_view_before_truncation(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("abcdefghij", encoding="utf-8")

    result = ReadFileTool().run(
        {"path": "large.txt"},
        ToolContext(workspace_root=tmp_path, max_output_chars=5),
    )

    assert result.display.data["content"] == "abcde"
    assert result.display.data["truncated"] is True
    assert result.complete.data["content"] == "abcdefghij"
    assert result.complete.data["truncated"] is False


def test_file_tools_reject_outside_path(tmp_path: Path) -> None:
    result = ReadFileTool().run({"path": "../outside.txt"}, context(tmp_path))

    assert result.ok is False
    assert "工作区外" in result.message


def test_file_tools_reject_absolute_path(tmp_path: Path) -> None:
    result = WriteFileTool().run({"path": str(tmp_path / "a.txt"), "content": ""}, context(tmp_path))

    assert result.ok is False
    assert "相对路径" in result.message


def test_file_tools_reject_symlink_outside_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(outside)

    result = ReadFileTool().run({"path": "link.txt"}, context(tmp_path))

    assert result.ok is False


def test_write_file_writes_content(tmp_path: Path) -> None:
    result = WriteFileTool().run({"path": "nested/a.txt", "content": ""}, context(tmp_path))

    assert result.ok is True
    assert (tmp_path / "nested/a.txt").read_text(encoding="utf-8") == ""


def test_edit_file_replaces_unique_text(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello world", encoding="utf-8")

    result = EditFileTool().run(
        {"path": "a.txt", "old_text": "world", "new_text": "agent"},
        context(tmp_path),
    )

    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "hello agent"


def test_edit_file_refuses_zero_or_multiple_matches(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("one one", encoding="utf-8")

    zero = EditFileTool().run({"path": "a.txt", "old_text": "two", "new_text": "x"}, context(tmp_path))
    multiple = EditFileTool().run({"path": "a.txt", "old_text": "one", "new_text": "x"}, context(tmp_path))

    assert zero.ok is False
    assert multiple.ok is False
    assert path.read_text(encoding="utf-8") == "one one"
