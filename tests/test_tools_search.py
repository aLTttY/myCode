from pathlib import Path

from mycode.tools.search import FindFilesTool, SearchCodeTool
from mycode.types import ToolContext


def context(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace_root=tmp_path, max_output_chars=100)


def test_find_files_matches_and_skips_dirs(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('x')", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("x", encoding="utf-8")

    result = FindFilesTool().run({"pattern": "*.py"}, context(tmp_path))

    assert result.ok is True
    assert result.data["matches"] == ["src/app.py"]


def test_search_code_text_and_regex(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("hello agent\nbye\n", encoding="utf-8")

    text = SearchCodeTool().run({"query": "agent"}, context(tmp_path))
    regex = SearchCodeTool().run({"query": "h.llo", "regex": True}, context(tmp_path))

    assert text.data["matches"][0]["line"] == 1
    assert regex.data["matches"][0]["path"] == "app.py"


def test_search_code_invalid_regex(tmp_path: Path) -> None:
    result = SearchCodeTool().run({"query": "[", "regex": True}, context(tmp_path))

    assert result.ok is False
    assert "正则" in result.message


def test_search_code_skips_binary_files(tmp_path: Path) -> None:
    (tmp_path / "bin.dat").write_bytes(b"\0agent")

    result = SearchCodeTool().run({"query": "agent"}, context(tmp_path))

    assert result.data["matches"] == []


def test_search_code_limits_scope(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src/app.py").write_text("agent", encoding="utf-8")
    (tmp_path / "docs/guide.md").write_text("agent", encoding="utf-8")

    result = SearchCodeTool().run({"query": "agent", "path": "src"}, context(tmp_path))

    assert [match["path"] for match in result.data["matches"]] == ["src/app.py"]


def test_search_code_rejects_outside_scope(tmp_path: Path) -> None:
    result = SearchCodeTool().run({"query": "agent", "path": "../outside"}, context(tmp_path))
    assert not result.ok
    assert "项目目录" in result.message
