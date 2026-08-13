from pathlib import Path

from mycode.agents.catalog import AgentCatalog
from mycode.agents.runtime import AgentRoleRuntime


def role(name: str, description: str, *, model: str = "inherit") -> str:
    return f"""---
name: {name}
description: {description}
allowed_tools: [read_file]
denied_tools: []
model: {model}
max_iterations: 4
permission_mode: strict
---
只读分析代码。
"""


def write_role(root: Path, filename: str, content: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(content, encoding="utf-8")


def test_source_precedence_and_plugin_order(tmp_path: Path) -> None:
    user = tmp_path / "user"
    plugin_one = tmp_path / "plugin-one"
    plugin_two = tmp_path / "plugin-two"
    write_role(plugin_one, "same.md", role("same", "plugin one"))
    write_role(plugin_two, "same.md", role("same", "plugin two"))
    write_role(user, "same.md", role("same", "user"))
    write_role(tmp_path / ".mycode" / "agents", "same.md", role("same", "project"))
    catalog = AgentCatalog(
        tmp_path,
        user_agents_root=user,
        builtin_texts={"same.md": role("same", "builtin")},
        plugin_roots=(plugin_one, plugin_two),
    )

    snapshot = catalog.load_initial({"read_file"}, {})

    assert snapshot.definitions["same"].description == "project"
    assert any(item.code == "shadowed_definition" for item in snapshot.diagnostics)


def test_first_plugin_wins_and_reports_override(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_role(first, "one.md", role("same", "first"))
    write_role(second, "two.md", role("same", "second"))
    catalog = AgentCatalog(
        tmp_path,
        user_agents_root=tmp_path / "missing",
        builtin_texts={},
        plugin_roots=(first, second),
    )

    snapshot = catalog.load_initial({"read_file"}, {})

    assert snapshot.definitions["same"].description == "first"
    assert any(item.code == "plugin_override" for item in snapshot.diagnostics)


def test_invalid_high_priority_role_falls_back(tmp_path: Path) -> None:
    project = tmp_path / ".mycode" / "agents"
    write_role(project, "bad.md", role("same", "bad").replace("[read_file]", "[unknown]"))
    catalog = AgentCatalog(
        tmp_path,
        user_agents_root=tmp_path / "missing",
        builtin_texts={"same.md": role("same", "builtin")},
    )

    snapshot = catalog.load_initial({"read_file"}, {})

    assert snapshot.definitions["same"].description == "builtin"
    assert any(item.code == "unknown_tool" for item in snapshot.diagnostics)


def test_missing_model_alias_only_invalidates_referencing_role(tmp_path: Path) -> None:
    project = tmp_path / ".mycode" / "agents"
    write_role(project, "fast.md", role("fast", "fast", model="haiku"))
    write_role(project, "normal.md", role("normal", "normal"))
    catalog = AgentCatalog(tmp_path, user_agents_root=tmp_path / "missing", builtin_texts={})

    snapshot = catalog.load_initial({"read_file"}, {})

    assert set(snapshot.definitions) == {"normal"}
    assert any(item.code == "missing_model_alias" for item in snapshot.diagnostics)


def test_refresh_and_runtime_keep_old_definition_snapshot(tmp_path: Path) -> None:
    project = tmp_path / ".mycode" / "agents"
    entry = project / "role.md"
    write_role(project, "role.md", role("role", "old"))
    catalog = AgentCatalog(tmp_path, user_agents_root=tmp_path / "missing", builtin_texts={})
    initial = catalog.load_initial({"read_file"}, {})
    runtime = AgentRoleRuntime(initial)
    held = runtime.definition("role")
    entry.write_text(role("role", "new and longer"), encoding="utf-8")

    report = catalog.refresh(runtime.snapshot, {"read_file"}, {})
    runtime.publish(report.snapshot)

    assert report.changed is True
    assert runtime.definition("role").description == "new and longer"
    assert held.description == "old"


def test_symlink_role_is_diagnosed_without_blocking_other_roles(tmp_path: Path) -> None:
    project = tmp_path / ".mycode" / "agents"
    write_role(project, "valid.md", role("valid", "valid"))
    outside = tmp_path / "outside.md"
    outside.write_text(role("linked", "linked"), encoding="utf-8")
    (project / "linked.md").symlink_to(outside)
    catalog = AgentCatalog(
        tmp_path, user_agents_root=tmp_path / "missing", builtin_texts={}
    )

    snapshot = catalog.load_initial({"read_file"}, {})

    assert set(snapshot.definitions) == {"valid"}
    assert any(item.code == "symlink_entry" for item in snapshot.diagnostics)
