from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mycode.skills.models import (
    SkillDefinition,
    SkillSnapshot,
    SkillToolDefinition,
    SkillValidationError,
    immutable_mapping,
)
from mycode.skills.runtime import SkillRuntime
from mycode.tools.base import result_ok
from mycode.tools.registry import create_default_registry
from mycode.types import ToolSpec


def _definition(
    name: str,
    *,
    source: str = "builtin",
    source_id: str | None = None,
    allowed: tuple[str, ...] = ("read_file",),
    mode: str = "shared",
    fingerprint: str | None = None,
    dedicated: tuple[SkillToolDefinition, ...] = (),
) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description=f"{name} description",
        allowed_tools=allowed,
        mode=mode,
        history=0 if mode == "isolated" else None,
        model=None,
        sop=f"{name} sop",
        compiled_sop=f"{name} compiled",
        source=source,
        source_id=source_id or f"{source}:{name}",
        package_root=None,
        dedicated_tools=dedicated,
        fingerprint=fingerprint or f"fp-{name}",
    )


def _snapshot(*definitions: SkillDefinition) -> SkillSnapshot:
    return SkillSnapshot(
        definitions=immutable_mapping({item.name: item for item in definitions}),
        dedicated_tools=immutable_mapping(
            {tool.exposed_name: tool for item in definitions for tool in item.dedicated_tools}
        ),
        fingerprint="snapshot-" + "-".join(item.fingerprint for item in definitions),
    )


class FakeTool:
    def __init__(self, definition: SkillToolDefinition) -> None:
        self.spec = ToolSpec(definition.exposed_name, definition.description, dict(definition.parameters))

    def run(self, arguments, context):
        return result_ok("ok")


def test_catalog_only_lists_unloaded_names_and_descriptions() -> None:
    first = _definition("first")
    second = _definition("second")
    runtime = SkillRuntime(_snapshot(first, second))

    assert "first description" in runtime.catalog_prompt()
    assert "first sop" not in runtime.catalog_prompt()
    runtime.activate_shared("first")
    assert "first" not in runtime.catalog_prompt()
    assert runtime.active_prompt() == ("### Skill `first`\nfirst compiled",)


def test_shared_activation_is_ordered_and_deduplicated() -> None:
    runtime = SkillRuntime(_snapshot(_definition("one"), _definition("two")))

    assert runtime.activate_shared("two").newly_activated
    assert runtime.activate_shared("one").newly_activated
    assert not runtime.activate_shared("two").newly_activated
    assert runtime.active_names() == ("two", "one")


def test_activate_shared_rejects_unknown_and_isolated() -> None:
    runtime = SkillRuntime(_snapshot(_definition("review", mode="isolated")))
    with pytest.raises(SkillValidationError, match="未知"):
        runtime.activate_shared("missing")
    with pytest.raises(SkillValidationError, match="不是共享"):
        runtime.activate_shared("review")


def test_registry_projection_uses_union_and_plan_intersection() -> None:
    base = create_default_registry()
    runtime = SkillRuntime(
        _snapshot(
            _definition("reader", allowed=("read_file", "search_code")),
            _definition("runner", allowed=("run_command",)),
        )
    )
    runtime.activate_shared("reader")
    runtime.activate_shared("runner")

    assert set(runtime.project_registry(base, "default").names()) == {
        "read_file",
        "search_code",
        "run_command",
    }
    assert set(runtime.project_registry(base, "plan").names()) == {"read_file", "search_code"}


def test_no_activation_preserves_full_registry_and_plan_is_readonly() -> None:
    base = create_default_registry()
    runtime = SkillRuntime(_snapshot(_definition("demo")))
    assert runtime.project_registry(base, "default").names() == base.names()
    assert set(runtime.project_registry(base, "plan").names()) == {
        "read_file",
        "find_files",
        "search_code",
        "read_git_changes",
    }


def test_dedicated_tool_only_appears_when_execution_skill_active(tmp_path: Path) -> None:
    tool = SkillToolDefinition(
        "lookup",
        "demo__lookup",
        "lookup",
        immutable_mapping({"type": "object"}),
        tmp_path / "lookup.py",
        "tool-fp",
    )
    definition = _definition("demo", allowed=("demo__lookup",), dedicated=(tool,))
    runtime = SkillRuntime(_snapshot(definition), dedicated_tool_factory=FakeTool)
    base = create_default_registry()
    assert "demo__lookup" not in runtime.project_registry(base, "default").names()

    runtime.activate_shared("demo")
    assert runtime.project_registry(base, "default").names() == ("demo__lookup",)
    assert runtime.project_registry(base, "plan").names() == ()


def test_publish_same_source_updates_but_lower_fallback_deactivates() -> None:
    original = _definition("demo", source="project", source_id="project:demo", fingerprint="one")
    runtime = SkillRuntime(_snapshot(original))
    runtime.activate_shared("demo")

    updated = replace(original, compiled_sop="new", fingerprint="two")
    report = runtime.publish(_snapshot(updated))
    assert report.replaced == ("demo",)
    assert runtime.active_prompt() == ("### Skill `demo`\nnew",)

    fallback = _definition("demo", source="user", source_id="user:demo", fingerprint="three")
    report = runtime.publish(_snapshot(fallback))
    assert report.deactivated == ("demo",)
    assert runtime.active_names() == ()


def test_publish_higher_priority_override_keeps_activation() -> None:
    builtin = _definition("demo", source="builtin", source_id="builtin:demo", fingerprint="one")
    runtime = SkillRuntime(_snapshot(builtin))
    runtime.activate_shared("demo")
    project = _definition("demo", source="project", source_id="project:demo", fingerprint="two")

    report = runtime.publish(_snapshot(project))
    assert report.replaced == ("demo",)
    assert runtime.active_names() == ("demo",)


def test_reset_clears_shared_but_isolated_root_remains() -> None:
    root = _definition("review", mode="isolated")
    helper = _definition("helper")
    runtime = SkillRuntime.for_isolated(_snapshot(root, helper), root)
    runtime.activate_shared("helper")
    runtime.reset()
    assert runtime.active_names() == ("review",)
