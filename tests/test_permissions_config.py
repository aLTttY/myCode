from pathlib import Path

import pytest
import yaml

from mycode.permissions.config import LocalRuleStore, PermissionConfigLoader
from mycode.types import ConfigError


TOOLS = {"read_file", "write_file", "edit_file", "run_command", "find_files", "search_code"}


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_loads_three_layers_and_resolves_mode_priority(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    write(home / ".mycode/permissions.yaml", "mode: strict\nallow:\n  - 'read_file(**)'\n")
    write(workspace / ".mycode/permissions.yaml", "mode: allow\n")
    write(workspace / ".mycode/permissions.local.yaml", "mode: default\n")

    loaded = PermissionConfigLoader(TOOLS, home).load(workspace)

    assert loaded.effective_mode == "default"
    assert loaded.user.rules[0].tool == "read_file"
    assert PermissionConfigLoader(TOOLS, home).load(workspace, "strict").effective_mode == "strict"


def test_missing_files_are_empty_layers(tmp_path: Path) -> None:
    loaded = PermissionConfigLoader(TOOLS, tmp_path / "home").load(tmp_path / "workspace")
    assert loaded.effective_mode == "default"
    assert not loaded.user.rules and not loaded.project.rules and not loaded.local.rules


def test_manually_written_local_rules_are_loaded(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    write(
        workspace / ".mycode/permissions.local.yaml",
        "allow:\n  - 'run_command(git status)'\ndeny:\n  - 'write_file(.env)'\n",
    )

    loaded = PermissionConfigLoader(TOOLS, tmp_path / "home").load(workspace)

    assert [(rule.tool, rule.effect) for rule in loaded.local.rules] == [
        ("run_command", "allow"),
        ("write_file", "deny"),
    ]


@pytest.mark.parametrize(
    "content",
    [
        "unknown: true\n",
        "mode: unsafe\n",
        "allow: read_file(**)\n",
        "allow:\n  - missing(*)\n",
        "allow:\n  - invalid\n",
        "mode: strict\nmode: allow\n",
        "[broken",
    ],
)
def test_invalid_configuration_fails_closed(tmp_path: Path, content: str) -> None:
    workspace = tmp_path / "workspace"
    write(workspace / ".mycode/permissions.yaml", content)
    with pytest.raises(ConfigError):
        PermissionConfigLoader(TOOLS, tmp_path / "home").load(workspace)


def test_local_store_appends_exact_allow_without_touching_other_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    local_path = workspace / ".mycode/permissions.local.yaml"
    project_path = workspace / ".mycode/permissions.yaml"
    write(local_path, "mode: default\ndeny:\n  - 'write_file(.env)'\n")
    write(project_path, "mode: strict\n")
    before_project = project_path.read_text(encoding="utf-8")
    store = LocalRuleStore(local_path, TOOLS)

    store.add_exact_allow("run_command", "git status")
    store.add_exact_allow("run_command", "git status")

    raw = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    assert raw["allow"] == ["run_command(git status)"]
    assert raw["deny"] == ["write_file(.env)"]
    assert project_path.read_text(encoding="utf-8") == before_project


def test_configured_mcp_namespace_rule_loads_when_server_is_offline(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    write(
        workspace / ".mycode/permissions.yaml",
        "allow:\n  - 'github__create-issue(call)'\n",
    )

    loaded = PermissionConfigLoader(
        TOOLS,
        tmp_path / "home",
        mcp_tool_prefixes=("github__",),
    ).load(workspace)

    assert loaded.project.rules[0].tool == "github__create-issue"


def test_unconfigured_dynamic_namespace_rule_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    write(
        workspace / ".mycode/permissions.yaml",
        "allow:\n  - 'unknown__tool(call)'\n",
    )

    with pytest.raises(ConfigError, match="未知工具"):
        PermissionConfigLoader(TOOLS, tmp_path / "home").load(workspace)
