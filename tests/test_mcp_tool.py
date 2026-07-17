from __future__ import annotations

from types import SimpleNamespace

import pytest

from mycode.mcp.models import MCPManagerError, MCPRemoteTool
from mycode.mcp.tool import MCPTool
from mycode.permissions.models import PermissionConfigSet, PermissionLayer
from mycode.permissions.service import PermissionService
from mycode.tools.executor import ToolExecutor
from mycode.tools.registry import ToolRegistry
from mycode.types import ToolCall, ToolContext


def remote() -> MCPRemoteTool:
    return MCPRemoteTool(
        server_name="alpha",
        remote_name="echo",
        exposed_name="alpha__echo",
        description="Echo input",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )


def content(kind: str, **values):
    return SimpleNamespace(type=kind, **values)


def result(*items, structured=None, is_error=False):
    return SimpleNamespace(content=list(items), structuredContent=structured, isError=is_error)


class FakeManager:
    def __init__(self, value=None, error=None) -> None:
        self.value = value or result(content("text", text="ok"))
        self.error = error
        self.calls = []

    def call_tool(self, server, name, arguments, timeout):
        self.calls.append((server, name, dict(arguments), timeout))
        if self.error:
            raise self.error
        return self.value


def context(tmp_path, *, max_output=20_000):
    return ToolContext(tmp_path, timeout_seconds=2.0, max_output_chars=max_output)


def test_exposes_remote_spec_and_calls_original_name(tmp_path) -> None:
    manager = FakeManager()
    tool = MCPTool(remote(), manager)  # type: ignore[arg-type]

    output = tool.run({"text": "hello"}, context(tmp_path))

    assert tool.spec.name == "alpha__echo"
    assert tool.spec.description == "Echo input"
    assert tool.spec.parameters["properties"]["text"]["type"] == "string"
    assert manager.calls == [("alpha", "echo", {"text": "hello"}, 2.0)]
    assert output.ok


def test_converts_text_and_structured_content(tmp_path) -> None:
    manager = FakeManager(
        result(
            content("text", text="one"),
            content("text", text="two"),
            structured={"count": 2},
        )
    )

    output = MCPTool(remote(), manager).run({}, context(tmp_path))  # type: ignore[arg-type]

    assert output.ok
    assert output.message == "one\ntwo"
    assert output.data["structured_content"] == {"count": 2}


def test_maps_remote_is_error_to_failed_result(tmp_path) -> None:
    manager = FakeManager(result(content("text", text="remote failed"), is_error=True))

    output = MCPTool(remote(), manager).run({}, context(tmp_path))  # type: ignore[arg-type]

    assert not output.ok
    assert output.message == "remote failed"
    assert output.data["reason"] == "remote_error"


@pytest.mark.parametrize("kind", ["image", "audio", "resource", "resource_link"])
def test_rejects_unsupported_content_without_payload(tmp_path, kind: str) -> None:
    manager = FakeManager(result(content("text", text="safe"), content(kind, data="secret-binary")))

    output = MCPTool(remote(), manager).run({}, context(tmp_path))  # type: ignore[arg-type]

    assert not output.ok
    assert output.data["reason"] == "unsupported_content"
    assert output.data["content_types"] == [kind]
    assert "secret-binary" not in output.message
    assert "secret-binary" not in repr(output.data)


def test_truncates_large_text_and_rejects_large_structured_content(tmp_path) -> None:
    text_manager = FakeManager(result(content("text", text="abcdefghij")))
    text_output = MCPTool(remote(), text_manager).run({}, context(tmp_path, max_output=5))  # type: ignore[arg-type]

    structured_manager = FakeManager(result(structured={"value": "abcdefghij"}))
    structured_output = MCPTool(remote(), structured_manager).run(  # type: ignore[arg-type]
        {},
        context(tmp_path, max_output=5),
    )

    assert text_output.ok and text_output.message == "abcde"
    assert text_output.data["truncated"] is True
    assert not structured_output.ok
    assert structured_output.data["reason"] == "result_too_large"


def test_maps_manager_error_without_leaking_details(tmp_path) -> None:
    error = MCPManagerError("server_unavailable", "alpha", "MCP Server `alpha` 当前不可用。")
    output = MCPTool(remote(), FakeManager(error=error)).run({}, context(tmp_path))  # type: ignore[arg-type]

    assert not output.ok
    assert output.data["reason"] == "server_unavailable"
    assert output.data["server"] == "alpha"


def test_permission_denial_prevents_remote_call(tmp_path) -> None:
    manager = FakeManager()
    registry = ToolRegistry()
    registry.register(MCPTool(remote(), manager))  # type: ignore[arg-type]
    permissions = PermissionService(
        PermissionConfigSet(
            user=PermissionLayer("user"),
            project=PermissionLayer("project"),
            local=PermissionLayer("local"),
            effective_mode="strict",
        ),
        mcp_tool_prefixes=("alpha__",),
    )
    executor = ToolExecutor(registry, context(tmp_path), permissions)

    output = executor.execute(ToolCall("1", "alpha__echo", {"text": "hello"}))

    assert not output.ok
    assert manager.calls == []
