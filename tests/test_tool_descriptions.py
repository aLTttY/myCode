from __future__ import annotations

from mycode.tools.descriptions import reinforce_tool_spec, reinforce_tool_specs
from mycode.types import ToolSpec


def test_reinforce_tool_spec_adds_dedicated_tool_rules() -> None:
    spec = reinforce_tool_spec(ToolSpec(name="read_file", description="Read.", parameters={"type": "object"}))

    assert "Use this tool first" in spec.description
    assert "workspace" in spec.description


def test_reinforce_edit_file_mentions_read_before_edit() -> None:
    spec = reinforce_tool_spec(ToolSpec(name="edit_file", description="Edit.", parameters={"type": "object"}))

    assert "Before editing" in spec.description
    assert "read" in spec.description


def test_reinforce_tool_spec_preserves_name_and_schema() -> None:
    original = ToolSpec(name="search_code", description="Search.", parameters={"type": "object"})
    spec = reinforce_tool_spec(original)

    assert spec.name == original.name
    assert spec.parameters is original.parameters


def test_reinforce_tool_specs_returns_tuple() -> None:
    specs = reinforce_tool_specs([ToolSpec(name="unknown", description="Unknown.", parameters={})])

    assert isinstance(specs, tuple)
    assert specs[0].description == "Unknown."
