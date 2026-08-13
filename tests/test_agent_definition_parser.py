from pathlib import Path

import pytest

from mycode.agents.parser import AgentDefinitionError, parse_agent_path, parse_agent_text


VALID = """---
name: reviewer
description: 审查当前改动
allowed_tools: [read_file, search_code]
denied_tools: []
model: inherit
max_iterations: 8
permission_mode: strict
---
你是只读审查 Agent。
请给出证据。
"""


def test_parses_complete_agent_definition() -> None:
    definition = parse_agent_text(VALID, source="project", source_id="role.md")

    assert definition.name == "reviewer"
    assert definition.description == "审查当前改动"
    assert definition.allowed_tools == ("read_file", "search_code")
    assert definition.denied_tools == ()
    assert definition.model == "inherit"
    assert definition.max_iterations == 8
    assert definition.permission_mode == "strict"
    assert definition.system_prompt == "你是只读审查 Agent。\n请给出证据。"
    assert len(definition.fingerprint) == 64
    assert definition.isolation == "shared"


def test_parses_worktree_isolation() -> None:
    definition = parse_agent_text(
        VALID.replace("permission_mode: strict", "permission_mode: strict\nisolation: worktree"),
        source="project",
        source_id="role.md",
    )

    assert definition.isolation == "worktree"


def test_rejects_invalid_isolation() -> None:
    with pytest.raises(AgentDefinitionError) as caught:
        parse_agent_text(
            VALID.replace("permission_mode: strict", "permission_mode: strict\nisolation: container"),
            source="project",
            source_id="role.md",
        )

    assert caught.value.code == "invalid_isolation"


def test_rejects_explicit_shared_isolation() -> None:
    with pytest.raises(AgentDefinitionError) as caught:
        parse_agent_text(
            VALID.replace("permission_mode: strict", "permission_mode: strict\nisolation: shared"),
            source="project",
            source_id="role.md",
        )

    assert caught.value.code == "invalid_isolation"


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        ("description: 审查当前改动\n", "", "missing_field"),
        ("permission_mode: strict", "permission_mode: bypass", "invalid_permission_mode"),
        ("model: inherit", "model: mini", "invalid_model"),
        ("max_iterations: 8", "max_iterations: false", "invalid_max_iterations"),
        ("denied_tools: []", "denied_tools: [read_file]", "tool_list_overlap"),
        ("allowed_tools: [read_file, search_code]", "allowed_tools: [Agent]", "globally_forbidden_tool"),
        ("name: reviewer", "name: Reviewer", "invalid_name"),
    ],
)
def test_rejects_invalid_agent_definition(old: str, new: str, code: str) -> None:
    with pytest.raises(AgentDefinitionError) as caught:
        parse_agent_text(VALID.replace(old, new), source="project", source_id="role.md")

    assert caught.value.code == code


def test_rejects_duplicate_yaml_key() -> None:
    text = VALID.replace("name: reviewer", "name: reviewer\nname: duplicate")

    with pytest.raises(AgentDefinitionError) as caught:
        parse_agent_text(text, source="project", source_id="role.md")

    assert caught.value.code == "invalid_yaml"


def test_rejects_symlink_entry(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text(VALID, encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)

    with pytest.raises(AgentDefinitionError) as caught:
        parse_agent_path(link, source="project", source_id="link.md")

    assert caught.value.code == "symlink_entry"
