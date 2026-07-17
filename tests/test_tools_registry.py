import pytest

from mycode.tools.registry import ToolRegistry, create_default_registry, is_valid_tool_name
from mycode.types import ToolError, ToolSpec


def test_default_registry_registers_six_tools() -> None:
    registry = create_default_registry()

    assert {spec.name for spec in registry.tool_specs()} == {
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "find_files",
        "search_code",
    }


def test_registry_lookup_and_unknown_tool() -> None:
    registry = create_default_registry()

    assert registry.get("read_file").spec.name == "read_file"
    with pytest.raises(ToolError, match="未知工具"):
        registry.get("missing")


def test_registry_openai_tool_schema() -> None:
    tools = create_default_registry().as_openai_tools()

    assert tools[0]["type"] == "function"
    assert "parameters" in tools[0]["function"]


def test_registry_rejects_duplicate_tool() -> None:
    registry = ToolRegistry()
    tool = create_default_registry().get("read_file")
    registry.register(tool)

    with pytest.raises(ToolError, match="已注册"):
        registry.register(tool)


def test_tool_name_validation_supports_mcp_names() -> None:
    assert is_valid_tool_name("github__create-issue")
    assert is_valid_tool_name("x" * 64)
    assert not is_valid_tool_name("invalid.name")
    assert not is_valid_tool_name("x" * 65)


def test_registry_rejects_invalid_tool_name() -> None:
    class InvalidTool:
        spec = ToolSpec("invalid.name", "invalid", {"type": "object"})

        def run(self, arguments, context):  # pragma: no cover - registration fails first.
            raise AssertionError

    with pytest.raises(ToolError, match="工具名"):
        ToolRegistry().register(InvalidTool())
