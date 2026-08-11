from __future__ import annotations

from pathlib import Path

import pytest

from mycode.skills import SkillValidationError, parse_skill_path, parse_skill_text


def _skill_text(extra: str = "", body: str = "执行 {{input}}。") -> str:
    return (
        "---\n"
        "name: demo\n"
        "description: 演示能力\n"
        "allowed_tools: [read_file]\n"
        "mode: shared\n"
        f"{extra}"
        "---\n"
        f"{body}\n"
    )


def test_parse_shared_skill_and_compile_input_reference() -> None:
    skill = parse_skill_text(_skill_text(), source="project", source_id="demo.md")

    assert skill.name == "demo"
    assert skill.allowed_tools == ("read_file",)
    assert skill.history is None
    assert skill.model is None
    assert "{{input}}" in skill.sop
    assert "{{input}}" not in skill.compiled_sop
    assert "user 角色消息" in skill.compiled_sop


def test_parse_isolated_skill_requires_history_and_accepts_model() -> None:
    text = """---
name: review
description: 审查改动
allowed_tools: []
mode: isolated
history: 2
model: model-x
---
审查当前输入。
"""
    skill = parse_skill_text(text, source="user", source_id="review.md")
    assert skill.history == 2
    assert skill.model == "model-x"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("name: demo", "missing_frontmatter"),
        ("---\nname: [\n---\nbody", "invalid_yaml"),
        (_skill_text(body=""), "empty_sop"),
        (_skill_text("unknown: true\n"), "unknown_field"),
        (_skill_text("history: 0\n"), "shared_isolated_field"),
        (_skill_text("model: x\n"), "shared_isolated_field"),
        (_skill_text().replace("allowed_tools: [read_file]", "allowed_tools: read_file"), "invalid_allowed_tools"),
        (_skill_text().replace("name: demo", "name: Help"), "invalid_name"),
    ],
)
def test_strict_frontmatter_errors(text: str, code: str) -> None:
    with pytest.raises(SkillValidationError) as caught:
        parse_skill_text(text, source="project", source_id="bad.md")
    assert caught.value.code == code


@pytest.mark.parametrize("history", ["-1", "true", "1.5", '"2"'])
def test_isolated_history_must_be_nonnegative_integer(history: str) -> None:
    text = f"""---
name: isolated
description: 独立能力
allowed_tools: []
mode: isolated
history: {history}
---
执行。
"""
    with pytest.raises(SkillValidationError) as caught:
        parse_skill_text(text, source="project", source_id="bad.md")
    assert caught.value.code == "invalid_history"


def test_directory_skill_parses_namespaced_tool(tmp_path: Path) -> None:
    package = tmp_path / "demo"
    tools = package / "tools"
    tools.mkdir(parents=True)
    (package / "SKILL.md").write_text(_skill_text().replace("[read_file]", "[demo__lookup]"), encoding="utf-8")
    (tools / "lookup.yaml").write_text(
        """name: lookup
description: 查询资料
parameters:
  type: object
  properties:
    query: {type: string}
  required: [query]
script: lookup.py
""",
        encoding="utf-8",
    )
    (tools / "lookup.py").write_text("print('{}')\n", encoding="utf-8")

    skill = parse_skill_path(package / "SKILL.md", source="project", source_id="demo/SKILL.md")

    assert skill.package_root == package.resolve()
    assert len(skill.dedicated_tools) == 1
    tool = skill.dedicated_tools[0]
    assert tool.local_name == "lookup"
    assert tool.exposed_name == "demo__lookup"
    assert tool.parameters["type"] == "object"


def test_directory_tool_rejects_unknown_field(tmp_path: Path) -> None:
    package = tmp_path / "demo"
    tools = package / "tools"
    tools.mkdir(parents=True)
    (package / "SKILL.md").write_text(_skill_text(), encoding="utf-8")
    (tools / "bad.yaml").write_text(
        "name: bad\ndescription: bad\nparameters: {type: object}\nscript: bad.py\nextra: true\n",
        encoding="utf-8",
    )
    (tools / "bad.py").write_text("print('{}')\n", encoding="utf-8")

    with pytest.raises(SkillValidationError) as caught:
        parse_skill_path(package / "SKILL.md", source="project", source_id="demo/SKILL.md")
    assert caught.value.code == "unknown_tool_field"


def test_directory_tool_rejects_script_escape(tmp_path: Path) -> None:
    package = tmp_path / "demo"
    tools = package / "tools"
    tools.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("print('{}')\n", encoding="utf-8")
    (package / "SKILL.md").write_text(_skill_text(), encoding="utf-8")
    (tools / "bad.yaml").write_text(
        "name: bad\ndescription: bad\nparameters: {type: object}\nscript: ../../outside.py\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillValidationError) as caught:
        parse_skill_path(package / "SKILL.md", source="project", source_id="demo/SKILL.md")
    assert caught.value.code == "tool_script_escape"


def test_entry_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text(_skill_text(), encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)

    with pytest.raises(SkillValidationError) as caught:
        parse_skill_path(link, source="project")
    assert caught.value.code == "symlink_entry"


def test_directory_tool_rejects_script_symlink(tmp_path: Path) -> None:
    package = tmp_path / "demo"
    tools = package / "tools"
    tools.mkdir(parents=True)
    target = package / "target.py"
    target.write_text("print('{}')\n", encoding="utf-8")
    (tools / "link.py").symlink_to(target)
    (package / "SKILL.md").write_text(_skill_text(), encoding="utf-8")
    (tools / "link.yaml").write_text(
        "name: link\ndescription: link\nparameters: {type: object}\nscript: link.py\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillValidationError) as caught:
        parse_skill_path(package / "SKILL.md", source="project", source_id="demo/SKILL.md")
    assert caught.value.code == "missing_tool_script"
