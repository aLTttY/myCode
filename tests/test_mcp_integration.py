from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from mycode.agent.config import AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.mcp import MCPManager, MCPTool
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest
from mycode.tools.registry import ToolRegistry
from mycode.types import (
    HTTPMCPServerConfig,
    StdioMCPServerConfig,
    StreamEvent,
    ToolContext,
)


FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "mcp_test_server.py"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("HTTP MCP fixture exited before readiness")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("HTTP MCP fixture readiness timed out")


@pytest.fixture(params=(False, True), ids=("sse", "json"))
def http_server(request: pytest.FixtureRequest) -> Iterator[str]:
    port = _free_port()
    command = [
        sys.executable,
        str(FIXTURE_SERVER),
        "--transport",
        "http",
        "--port",
        str(port),
    ]
    if request.param:
        command.append("--json-response")
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(process, port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _text(result: object) -> str:
    content = getattr(result, "content")
    return "\n".join(item.text for item in content if item.type == "text")


def test_real_stdio_discovers_calls_and_inherits_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_FIXTURE_VALUE", "parent")
    config = StdioMCPServerConfig(
        "local",
        "stdio",
        sys.executable,
        (str(FIXTURE_SERVER), "--transport", "stdio"),
        {"MCP_FIXTURE_VALUE": "configured"},
    )
    manager = MCPManager((config,))
    try:
        tools, warnings = manager.discover()
        result = manager.call_tool("local", "environment", {}, 2.0)
        first_pid = _text(manager.call_tool("local", "process_id", {}, 2.0))
        second_pid = _text(manager.call_tool("local", "process_id", {}, 2.0))

        assert warnings == []
        assert "local__echo" in {tool.exposed_name for tool in tools}
        assert _text(result) == "configured"
        assert first_pid == second_pid
    finally:
        manager.close()
    assert not manager.is_running


def test_real_streamable_http_supports_sse_and_json(http_server: str) -> None:
    config = HTTPMCPServerConfig(
        "remote",
        "http",
        http_server,
        {"X-MCP-Test": "header-sentinel"},
    )
    manager = MCPManager((config,))
    try:
        tools, warnings = manager.discover()
        result = manager.call_tool("remote", "echo", {"text": "hello"}, 2.0)
        structured = manager.call_tool("remote", "structured", {"value": "v"}, 2.0)
        header = manager.call_tool("remote", "http_header", {}, 2.0)

        assert warnings == []
        assert "remote__echo" in {tool.exposed_name for tool in tools}
        assert _text(result) == "hello"
        assert structured.structuredContent == {"value": "v", "nested": {"ok": True}}
        assert _text(header) == "header-sentinel"
    finally:
        manager.close()
    assert not manager.is_running


def test_real_mixed_servers_isolate_failure_and_pair_concurrent_calls(
    http_server: str,
) -> None:
    unavailable_port = _free_port()
    stdio = StdioMCPServerConfig(
        "local",
        "stdio",
        sys.executable,
        (str(FIXTURE_SERVER), "--transport", "stdio"),
    )
    http = HTTPMCPServerConfig("remote", "http", http_server)
    bad = HTTPMCPServerConfig("broken", "http", f"http://127.0.0.1:{unavailable_port}/mcp")
    manager = MCPManager((stdio, http, bad), startup_timeout_seconds=2.0)
    try:
        tools, warnings = manager.discover()

        async def run_calls() -> list[object]:
            loop = asyncio.get_running_loop()
            slow = loop.run_in_executor(
                None,
                manager.call_tool,
                "remote",
                "delayed",
                {"label": "slow", "delay": 0.15},
                2.0,
            )
            fast = loop.run_in_executor(
                None,
                manager.call_tool,
                "remote",
                "delayed",
                {"label": "fast", "delay": 0.0},
                2.0,
            )
            return list(await asyncio.gather(slow, fast))

        results = asyncio.run(run_calls())

        names = {tool.exposed_name for tool in tools}
        assert "local__echo" in names and "remote__echo" in names
        assert [warning.server_name for warning in warnings] == ["broken"]
        assert [_text(result) for result in results] == ["slow", "fast"]
    finally:
        manager.close()
    assert not manager.is_running


class _ScriptedProvider:
    def __init__(self) -> None:
        self.calls: list[ChatRequest] = []

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamEvent]:
        self.calls.append(request)
        if len(self.calls) == 1:
            yield StreamEvent(
                type="tool_call_delta",
                tool_call_id="1",
                tool_name="local__echo",
                arguments_delta='{"text":"from-agent"}',
            )
            yield StreamEvent(type="tool_call_done", tool_call_id="1")
        else:
            yield StreamEvent(type="text_delta", text="done")
        yield StreamEvent(type="message_done")


def test_real_mcp_tool_runs_through_permission_and_agent(tmp_path: Path) -> None:
    config = StdioMCPServerConfig(
        "local",
        "stdio",
        sys.executable,
        (str(FIXTURE_SERVER), "--transport", "stdio"),
    )
    manager = MCPManager((config,))
    try:
        remote_tools, warnings = manager.discover()
        remote = next(tool for tool in remote_tools if tool.remote_name == "echo")
        registry = ToolRegistry()
        registry.register(MCPTool(remote, manager))
        provider = _ScriptedProvider()
        agent = AgentRunner(
            provider,
            registry,
            ToolContext(workspace_root=tmp_path, timeout_seconds=2.0),
            permission_service=PermissionService.with_mode(
                "allow",
                mcp_tool_prefixes=("local__",),
            ),
        )

        events = list(agent.run(AgentRequest("call echo")))

        assert warnings == []
        assert events[-1].stop_reason == "completed"
        assert len(provider.calls) == 2
        assert "from-agent" in provider.calls[1].messages[-1].content
    finally:
        manager.close()
    assert not manager.is_running
