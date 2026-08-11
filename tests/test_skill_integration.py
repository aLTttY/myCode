from __future__ import annotations

from pathlib import Path

from mycode import cli
from mycode.commands import create_default_command_registry
from mycode.permissions.service import PermissionService
from mycode.skills.catalog import SkillCatalog
from mycode.skills.commands import commands_from_snapshot
from mycode.skills.runtime import SkillRuntime
from mycode.tool_safety import SYSTEM_TOOLS
from mycode.tools.registry import create_default_registry


def write_skill(path: Path, *, description: str, sop: str, allowed: str = "read_file") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                "---",
                "name: demo",
                f"description: {description}",
                "allowed_tools:",
                f"  - {allowed}",
                "mode: shared",
                "---",
                sop,
            )
        ),
        encoding="utf-8",
    )


def setup_runtime(tmp_path: Path):
    tool_registry = create_default_registry()
    command_registry = create_default_command_registry()
    reserved = tuple(
        token
        for command in command_registry.commands(include_hidden=True)
        for token in (command.name, *command.aliases)
    )
    catalog = SkillCatalog(
        tmp_path,
        user_skills_root=tmp_path / "user-skills",
        builtin_texts={},
    )
    snapshot = catalog.load_initial(set(tool_registry.names()) | set(SYSTEM_TOOLS), reserved)
    runtime = SkillRuntime(snapshot)
    command_registry.replace_dynamic(commands_from_snapshot(snapshot))
    permission = PermissionService.with_mode("allow")
    return catalog, runtime, tool_registry, command_registry, permission, reserved


def test_hot_refresh_replaces_active_sop_and_command_metadata(tmp_path: Path) -> None:
    path = tmp_path / ".mycode" / "skills" / "demo.md"
    write_skill(path, description="first description", sop="FIRST SOP")
    catalog, runtime, tools, commands, permission, reserved = setup_runtime(tmp_path)
    runtime.activate_shared("demo")
    write_skill(path, description="second description", sop="SECOND SOP WITH MORE TEXT")

    cli._refresh_skills(catalog, runtime, tools, commands, permission, reserved)

    assert runtime.active_names() == ("demo",)
    assert "SECOND SOP WITH MORE TEXT" in runtime.active_prompt()[0]
    assert commands.resolve("demo").description == "second description"  # type: ignore[union-attr]


def test_hot_refresh_invalidates_one_skill_without_breaking_catalog(tmp_path: Path) -> None:
    path = tmp_path / ".mycode" / "skills" / "demo.md"
    write_skill(path, description="valid", sop="VALID SOP")
    catalog, runtime, tools, commands, permission, reserved = setup_runtime(tmp_path)
    runtime.activate_shared("demo")
    path.write_text("---\nname: demo\n---\nbroken", encoding="utf-8")

    cli._refresh_skills(catalog, runtime, tools, commands, permission, reserved)

    assert runtime.active_names() == ()
    assert commands.resolve("demo") is None
    assert runtime.snapshot.diagnostics


def test_hot_refresh_rejects_new_unknown_whitelist_but_keeps_other_skills(tmp_path: Path) -> None:
    path = tmp_path / ".mycode" / "skills" / "demo.md"
    write_skill(path, description="valid", sop="VALID SOP")
    catalog, runtime, tools, commands, permission, reserved = setup_runtime(tmp_path)
    write_skill(path, description="invalid", sop="INVALID SOP", allowed="missing_tool")

    cli._refresh_skills(catalog, runtime, tools, commands, permission, reserved)

    assert "demo" not in runtime.snapshot.definitions
    assert commands.resolve("demo") is None
    assert any(item.code == "unknown_allowed_tool" for item in runtime.snapshot.diagnostics)
