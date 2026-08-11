from __future__ import annotations

from pathlib import Path

import pytest

from mycode.skills import SkillCatalogError
from mycode.skills.catalog import SkillCatalog


def _skill(
    name: str,
    description: str,
    *,
    tools: str = "[]",
    mode: str = "shared",
    extra: str = "",
) -> str:
    return f"""---
name: {name}
description: {description}
allowed_tools: {tools}
mode: {mode}
{extra}---
执行 {name}。
"""


def _catalog(tmp_path: Path, builtins: dict[str, str] | None = None) -> SkillCatalog:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    user = tmp_path / "user-skills"
    return SkillCatalog(workspace, user_skills_root=user, builtin_texts=builtins or {})


def _write_project(catalog: SkillCatalog, name: str, text: str) -> Path:
    catalog.project_skills_root.mkdir(parents=True, exist_ok=True)
    path = catalog.project_skills_root / name
    path.write_text(text, encoding="utf-8")
    return path


def _write_user(catalog: SkillCatalog, name: str, text: str) -> Path:
    catalog.user_skills_root.mkdir(parents=True, exist_ok=True)
    path = catalog.user_skills_root / name
    path.write_text(text, encoding="utf-8")
    return path


def test_priority_project_then_user_then_builtin(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path, {"demo.md": _skill("demo", "内置")})
    user = _write_user(catalog, "demo.md", _skill("demo", "用户"))
    project = _write_project(catalog, "demo.md", _skill("demo", "项目"))

    snapshot = catalog.load_initial(set(), set())
    assert snapshot.definitions["demo"].description == "项目"

    project.unlink()
    snapshot = catalog.refresh(snapshot, set(), set()).snapshot
    assert snapshot.definitions["demo"].description == "用户"

    user.unlink()
    snapshot = catalog.refresh(snapshot, set(), set()).snapshot
    assert snapshot.definitions["demo"].description == "内置"


def test_invalid_high_priority_does_not_shadow_lower_valid(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path, {"demo.md": _skill("demo", "内置")})
    _write_project(catalog, "demo.md", "not frontmatter")

    snapshot = catalog.load_initial(set(), set())

    assert snapshot.definitions["demo"].description == "内置"
    assert snapshot.diagnostics[0].code == "missing_frontmatter"
    assert "not frontmatter" not in snapshot.diagnostics[0].message


def test_same_layer_duplicate_is_startup_error(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _write_project(catalog, "one.md", _skill("demo", "一"))
    _write_project(catalog, "two.md", _skill("demo", "二"))

    with pytest.raises(SkillCatalogError) as caught:
        catalog.load_initial(set(), set())
    assert "同层" in caught.value.user_message
    assert "one.md" in caught.value.user_message


def test_reserved_command_is_startup_error(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _write_project(catalog, "help.md", _skill("help", "冲突"))

    with pytest.raises(SkillCatalogError) as caught:
        catalog.load_initial(set(), {"help", "h"})
    assert "保留" in caught.value.user_message


def test_unknown_allowed_tool_is_startup_error(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _write_project(catalog, "demo.md", _skill("demo", "未知", tools="[missing_tool]"))

    with pytest.raises(SkillCatalogError) as caught:
        catalog.load_initial({"read_file"}, set())
    assert "missing_tool" in caught.value.user_message


def test_own_dedicated_tool_is_valid_but_other_skill_cannot_use_it(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    package = catalog.project_skills_root / "owner"
    tools = package / "tools"
    tools.mkdir(parents=True)
    (package / "SKILL.md").write_text(
        _skill("owner", "拥有工具", tools="[owner__lookup]"), encoding="utf-8"
    )
    (tools / "lookup.yaml").write_text(
        "name: lookup\ndescription: 查找\nparameters: {type: object}\nscript: lookup.py\n",
        encoding="utf-8",
    )
    (tools / "lookup.py").write_text("print('{}')\n", encoding="utf-8")

    snapshot = catalog.load_initial(set(), set())
    assert "owner__lookup" in snapshot.dedicated_tools

    _write_project(catalog, "borrower.md", _skill("borrower", "借用", tools="[owner__lookup]"))
    report = catalog.refresh(snapshot, set(), set())
    assert "borrower" not in report.snapshot.definitions
    assert any(item.code == "unknown_allowed_tool" for item in report.diagnostics)


def test_refresh_without_state_change_reuses_snapshot(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    _write_project(catalog, "demo.md", _skill("demo", "演示"))
    snapshot = catalog.load_initial(set(), set())

    report = catalog.refresh(snapshot, set(), set())

    assert not report.changed
    assert report.snapshot is snapshot


def test_runtime_duplicate_isolated_and_other_update_published(tmp_path: Path) -> None:
    catalog = _catalog(tmp_path)
    first = _write_project(catalog, "demo.md", _skill("demo", "旧"))
    snapshot = catalog.load_initial(set(), set())

    first.write_text(_skill("demo", "新一"), encoding="utf-8")
    _write_project(catalog, "duplicate.md", _skill("demo", "新二"))
    _write_project(catalog, "other.md", _skill("other", "其他"))
    report = catalog.refresh(snapshot, set(), set())

    assert report.changed
    assert "demo" not in report.snapshot.definitions
    assert report.snapshot.definitions["other"].description == "其他"
    assert any(item.code == "duplicate_name" for item in report.diagnostics)


def test_default_builtin_resources_are_packaged(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    catalog = SkillCatalog(workspace, user_skills_root=tmp_path / "none")

    snapshot = catalog.load_initial(
        {"read_git_changes", "read_file", "find_files", "search_code", "run_command"},
        {"help", "clear", "plan"},
    )

    assert set(snapshot.definitions) >= {"commit", "review", "test"}
    assert snapshot.definitions["review"].mode == "isolated"
    assert snapshot.definitions["review"].history == 0
    assert snapshot.definitions["commit"].mode == "shared"
