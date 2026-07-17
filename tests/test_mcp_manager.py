from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from mycode.mcp.manager import MCPManager
from mycode.mcp.models import MCPManagerError
from mycode.types import StdioMCPServerConfig


def server(name: str) -> StdioMCPServerConfig:
    return StdioMCPServerConfig(name, "stdio", "fake")


def tool(name: str, description: str = "demo", schema=None):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema=schema if schema is not None else {"type": "object"},
    )


def page(tools, cursor=None):
    return SimpleNamespace(tools=tools, nextCursor=cursor)


class FakeSession:
    def __init__(self, pages=None, *, initialize_error=None, delays=None) -> None:
        self.pages = pages or {None: page([])}
        self.initialize_error = initialize_error
        self.delays = delays or {}
        self.initialize_calls = 0
        self.call_names: list[str] = []

    async def initialize(self):
        self.initialize_calls += 1
        if self.initialize_error:
            raise self.initialize_error
        return SimpleNamespace(
            protocolVersion="2025-11-25",
            capabilities=SimpleNamespace(tools=SimpleNamespace()),
        )

    async def list_tools(self, cursor=None):
        return self.pages[cursor]

    async def call_tool(self, name, arguments=None, read_timeout_seconds=None):
        self.call_names.append(name)
        delay = self.delays.get(name, 0)
        if delay:
            await asyncio.sleep(delay)
        if name == "fail":
            raise RuntimeError("secret transport detail")
        return SimpleNamespace(name=name, arguments=arguments or {})


class FakeConnector:
    def __init__(self, sessions: dict[str, FakeSession]) -> None:
        self.sessions = sessions
        self.entered: list[str] = []
        self.exited: list[str] = []

    def __call__(self, config, timeout):
        @asynccontextmanager
        async def connect():
            self.entered.append(config.name)
            try:
                yield self.sessions[config.name]
            finally:
                self.exited.append(config.name)

        return connect()


def test_no_servers_does_not_start_thread() -> None:
    manager = MCPManager(())

    assert manager.discover() == ([], [])
    assert not manager.is_running
    manager.close()


def test_discovers_all_pages_and_reuses_cached_session() -> None:
    session = FakeSession(
        {
            None: page([tool("first")], "next"),
            "next": page([tool("second")]),
        }
    )
    connector = FakeConnector({"alpha": session})
    manager = MCPManager((server("alpha"),), connector=connector)
    try:
        tools, warnings = manager.discover()
        again, _ = manager.discover()
        result = manager.call_tool("alpha", "first", {"x": 1}, 1.0)

        assert [item.exposed_name for item in tools] == ["alpha__first", "alpha__second"]
        assert again == tools and warnings == []
        assert result.name == "first"
        assert connector.entered == ["alpha"]
        assert session.initialize_calls == 1
    finally:
        manager.close()
    assert connector.exited == ["alpha"]
    assert not manager.is_running


def test_server_failure_is_isolated_and_warning_is_sanitized() -> None:
    good = FakeSession({None: page([tool("ok")])})
    bad = FakeSession(initialize_error=RuntimeError("header-secret"))
    connector = FakeConnector({"good": good, "bad": bad})
    manager = MCPManager((server("good"), server("bad")), connector=connector)
    try:
        tools, warnings = manager.discover()

        assert [item.exposed_name for item in tools] == ["good__ok"]
        assert len(warnings) == 1 and warnings[0].server_name == "bad"
        assert warnings[0].stage == "initialize"
        assert "header-secret" not in warnings[0].message
    finally:
        manager.close()


def test_invalid_and_duplicate_remote_tools_are_skipped() -> None:
    session = FakeSession(
        {
            None: page(
                [
                    tool("valid"),
                    tool("invalid.name"),
                    tool("valid"),
                    tool("bad_schema", schema="not-object"),
                ]
            )
        }
    )
    manager = MCPManager((server("alpha"),), connector=FakeConnector({"alpha": session}))
    try:
        tools, warnings = manager.discover()

        assert [item.exposed_name for item in tools] == ["alpha__valid"]
        assert [warning.stage for warning in warnings].count("tool_validation") == 2
        assert [warning.stage for warning in warnings].count("registration") == 1
    finally:
        manager.close()


def test_repeated_cursor_fails_only_that_server() -> None:
    looping = FakeSession({None: page([], "same"), "same": page([], "same")})
    good = FakeSession({None: page([tool("ok")])})
    connector = FakeConnector({"loop": looping, "good": good})
    manager = MCPManager((server("loop"), server("good")), connector=connector)
    try:
        tools, warnings = manager.discover()

        assert [item.exposed_name for item in tools] == ["good__ok"]
        assert any(item.server_name == "loop" and item.stage == "list_tools" for item in warnings)
    finally:
        manager.close()


def test_concurrent_calls_keep_their_own_results() -> None:
    session = FakeSession({None: page([tool("slow"), tool("fast")])}, delays={"slow": 0.05})
    manager = MCPManager((server("alpha"),), connector=FakeConnector({"alpha": session}))
    try:
        manager.discover()

        async def run_calls():
            loop = asyncio.get_running_loop()
            slow = loop.run_in_executor(None, manager.call_tool, "alpha", "slow", {"id": 1}, 1.0)
            fast = loop.run_in_executor(None, manager.call_tool, "alpha", "fast", {"id": 2}, 1.0)
            return await asyncio.gather(slow, fast)

        results = asyncio.run(run_calls())

        assert [(item.name, item.arguments["id"]) for item in results] == [("slow", 1), ("fast", 2)]
    finally:
        manager.close()


def test_call_timeout_cancels_wait_and_manager_can_close() -> None:
    session = FakeSession({None: page([tool("slow")])}, delays={"slow": 1.0})
    manager = MCPManager((server("alpha"),), connector=FakeConnector({"alpha": session}))
    try:
        manager.discover()
        with pytest.raises(MCPManagerError, match="超时") as caught:
            manager.call_tool("alpha", "slow", {}, 0.15)
        assert caught.value.reason_code == "request_timeout"
    finally:
        manager.close()
    assert not manager.is_running


def test_failed_call_is_sanitized_and_does_not_reconnect() -> None:
    session = FakeSession({None: page([tool("fail")])})
    connector = FakeConnector({"alpha": session})
    manager = MCPManager((server("alpha"),), connector=connector)
    try:
        manager.discover()
        with pytest.raises(MCPManagerError) as caught:
            manager.call_tool("alpha", "fail", {}, 1.0)

        assert caught.value.reason_code == "call_failed"
        assert "secret" not in caught.value.user_message
        assert session.initialize_calls == 1
        assert connector.entered == ["alpha"]
    finally:
        manager.close()


def test_close_is_idempotent_and_rejects_new_calls() -> None:
    session = FakeSession({None: page([tool("ok")])})
    manager = MCPManager((server("alpha"),), connector=FakeConnector({"alpha": session}))
    manager.discover()

    manager.close()
    manager.close()

    with pytest.raises(MCPManagerError) as caught:
        manager.call_tool("alpha", "ok", {}, 1.0)
    assert caught.value.reason_code == "manager_closed"
