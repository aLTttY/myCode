from __future__ import annotations

from mycode.agent.tools import ToolBatcher, classify_tool, create_readonly_registry
from mycode.tools.registry import create_default_registry
from mycode.types import ToolCall


def test_classify_tools() -> None:
    assert classify_tool("read_file") == "read"
    assert classify_tool("find_files") == "read"
    assert classify_tool("search_code") == "read"
    assert classify_tool("write_file") == "side_effect"
    assert classify_tool("edit_file") == "side_effect"
    assert classify_tool("run_command") == "side_effect"
    assert classify_tool("unknown") == "side_effect"
    assert classify_tool("github__create_issue") == "side_effect"


def test_create_readonly_registry_contains_only_read_tools() -> None:
    registry = create_readonly_registry(create_default_registry())

    assert {spec.name for spec in registry.tool_specs()} == {"read_file", "find_files", "search_code"}


def test_batcher_groups_adjacent_tool_safety() -> None:
    calls = [
        ToolCall(id="1", name="read_file", arguments={}),
        ToolCall(id="2", name="find_files", arguments={}),
        ToolCall(id="3", name="write_file", arguments={}),
        ToolCall(id="4", name="search_code", arguments={}),
    ]

    batches = ToolBatcher().batch(calls)

    assert [batch.safety for batch in batches] == ["read", "side_effect", "read"]
    assert [[call.id for call in batch.calls] for batch in batches] == [["1", "2"], ["3"], ["4"]]
