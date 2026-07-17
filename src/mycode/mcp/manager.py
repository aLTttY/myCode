from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from mycode.tools.registry import is_valid_tool_name
from mycode.types import HTTPMCPServerConfig, MCPServerConfig, StdioMCPServerConfig

from .models import MCPDiscoveryWarning, MCPManagerError, MCPRemoteTool


class _SessionLike(Protocol):
    async def initialize(self) -> Any:
        ...

    async def list_tools(self, cursor: str | None = None) -> Any:
        ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
    ) -> CallToolResult:
        ...


SessionConnector = Callable[
    [MCPServerConfig, float],
    AbstractAsyncContextManager[_SessionLike],
]


@dataclass
class _ServerConnection:
    config: MCPServerConfig
    session: _SessionLike
    exit_stack: AsyncExitStack
    negotiated_protocol: str


class MCPManager:
    def __init__(
        self,
        servers: tuple[MCPServerConfig, ...],
        *,
        startup_timeout_seconds: float = 10.0,
        close_timeout_seconds: float = 5.0,
        connector: SessionConnector | None = None,
    ) -> None:
        self.servers = tuple(servers)
        self.startup_timeout_seconds = startup_timeout_seconds
        self.close_timeout_seconds = close_timeout_seconds
        self._connector = connector or _sdk_session
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._connections: dict[str, _ServerConnection] = {}
        self._closing = False
        self._closed = False
        self._discovered = False
        self._discovered_tools: tuple[MCPRemoteTool, ...] = ()
        self._discovery_warnings: tuple[MCPDiscoveryWarning, ...] = ()

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise MCPManagerError("manager_closed", "", "MCP Manager 已关闭。")
            if not self.servers or self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run_event_loop,
                name="mewcode-mcp-loop",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=self.startup_timeout_seconds):
            raise MCPManagerError("loop_start_timeout", "", "MCP 后台事件循环启动超时。")

    def discover(self) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
        with self._lock:
            if self._discovered:
                return list(self._discovered_tools), list(self._discovery_warnings)
            if self._closed or self._closing:
                raise MCPManagerError("manager_closed", "", "MCP Manager 已关闭。")
        if not self.servers:
            with self._lock:
                self._discovered = True
            return [], []

        self.start()
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(self._discover_all(), loop)
        outer_timeout = max(1.0, self.startup_timeout_seconds * 3 + 1.0)
        try:
            tools, warnings = future.result(timeout=outer_timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPManagerError("discovery_timeout", "", "MCP 工具发现超时。") from exc
        with self._lock:
            self._discovered = True
            self._discovered_tools = tuple(tools)
            self._discovery_warnings = tuple(warnings)
        return list(tools), list(warnings)

    def call_tool(
        self,
        server_name: str,
        remote_name: str,
        arguments: Mapping[str, object],
        timeout_seconds: float,
    ) -> CallToolResult:
        with self._lock:
            if self._closed or self._closing:
                raise MCPManagerError("manager_closed", server_name, f"MCP Server `{server_name}` 已关闭。")
            if server_name not in self._connections:
                raise MCPManagerError(
                    "server_unavailable",
                    server_name,
                    f"MCP Server `{server_name}` 当前不可用。",
                )
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool(server_name, remote_name, dict(arguments), timeout_seconds),
            loop,
        )
        local_timeout = max(0.05, timeout_seconds - 0.05)
        try:
            return future.result(timeout=local_timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPManagerError(
                "request_timeout",
                server_name,
                f"MCP Server `{server_name}` 工具调用超时。",
            ) from exc
        except MCPManagerError:
            raise
        except Exception as exc:
            raise MCPManagerError(
                "call_failed",
                server_name,
                f"MCP Server `{server_name}` 工具调用失败（{type(exc).__name__}）。",
            ) from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
            loop = self._loop
            thread = self._thread

        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._close_all(), loop)
            try:
                future.result(timeout=self.close_timeout_seconds)
            except FutureTimeoutError:
                future.cancel()
            finally:
                loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.close_timeout_seconds)
        with self._lock:
            self._connections.clear()
            self._closed = True
            self._closing = False

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread and thread.is_alive())

    def _run_event_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None or not loop.is_running():
            raise MCPManagerError("loop_unavailable", "", "MCP 后台事件循环不可用。")
        return loop

    async def _discover_all(
        self,
    ) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
        results = await asyncio.gather(
            *(self._connect_one(config) for config in self.servers),
            return_exceptions=True,
        )
        tools: list[MCPRemoteTool] = []
        warnings: list[MCPDiscoveryWarning] = []
        seen: set[str] = set()
        for config, result in zip(self.servers, results, strict=True):
            if isinstance(result, BaseException):
                warnings.append(
                    MCPDiscoveryWarning(
                        config.name,
                        "connect",
                        f"MCP Server `{config.name}` 连接失败（{type(result).__name__}）。",
                    )
                )
                continue
            server_tools, server_warnings = result
            warnings.extend(server_warnings)
            for tool in server_tools:
                if tool.exposed_name in seen:
                    warnings.append(
                        MCPDiscoveryWarning(
                            config.name,
                            "registration",
                            f"MCP 工具 `{tool.exposed_name}` 与先注册工具冲突，已跳过。",
                        )
                    )
                    continue
                seen.add(tool.exposed_name)
                tools.append(tool)
        return tools, warnings

    async def _connect_one(
        self,
        config: MCPServerConfig,
    ) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
        stack = AsyncExitStack()
        stage = "connect"
        try:
            session = await asyncio.wait_for(
                stack.enter_async_context(self._connector(config, self.startup_timeout_seconds)),
                timeout=self.startup_timeout_seconds,
            )
            stage = "initialize"
            initialized = await asyncio.wait_for(
                session.initialize(),
                timeout=self.startup_timeout_seconds,
            )
            tools_capability = getattr(getattr(initialized, "capabilities", None), "tools", None)
            if tools_capability is None:
                raise ValueError("server does not declare tools capability")
            protocol = str(getattr(initialized, "protocolVersion", ""))
            connection = _ServerConnection(config, session, stack, protocol)
            self._connections[config.name] = connection
            stage = "list_tools"
            tools, warnings = await self._list_all_tools(connection)
            return tools, warnings
        except Exception as exc:
            await stack.aclose()
            self._connections.pop(config.name, None)
            warning_stage = stage if stage in {"connect", "initialize", "list_tools"} else "connect"
            return [], [
                MCPDiscoveryWarning(
                    config.name,
                    warning_stage,  # type: ignore[arg-type]
                    f"MCP Server `{config.name}` {warning_stage} 失败（{type(exc).__name__}）。",
                )
            ]

    async def _list_all_tools(
        self,
        connection: _ServerConnection,
    ) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
        tools: list[MCPRemoteTool] = []
        warnings: list[MCPDiscoveryWarning] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await asyncio.wait_for(
                connection.session.list_tools(cursor=cursor),
                timeout=self.startup_timeout_seconds,
            )
            for remote in getattr(page, "tools", ()):
                remote_name = getattr(remote, "name", "")
                exposed_name = f"{connection.config.name}__{remote_name}"
                input_schema = getattr(remote, "inputSchema", None)
                if (
                    not isinstance(remote_name, str)
                    or not is_valid_tool_name(remote_name)
                    or not is_valid_tool_name(exposed_name)
                    or not isinstance(input_schema, dict)
                ):
                    warnings.append(
                        MCPDiscoveryWarning(
                            connection.config.name,
                            "tool_validation",
                            f"MCP Server `{connection.config.name}` 返回了非法工具，已跳过。",
                        )
                    )
                    continue
                description = getattr(remote, "description", None)
                if not isinstance(description, str) or not description:
                    description = (
                        f"MCP Server {connection.config.name} 提供的工具 {remote_name}。"
                    )
                tools.append(
                    MCPRemoteTool(
                        server_name=connection.config.name,
                        remote_name=remote_name,
                        exposed_name=exposed_name,
                        description=description,
                        input_schema=dict(input_schema),
                    )
                )
            next_cursor = getattr(page, "nextCursor", None)
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise ValueError("tools/list returned a repeated cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return tools, warnings

    async def _call_tool(
        self,
        server_name: str,
        remote_name: str,
        arguments: dict[str, object],
        timeout_seconds: float,
    ) -> CallToolResult:
        connection = self._connections.get(server_name)
        if connection is None:
            raise MCPManagerError(
                "server_unavailable",
                server_name,
                f"MCP Server `{server_name}` 当前不可用。",
            )
        try:
            return await connection.session.call_tool(
                remote_name,
                arguments,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            )
        except Exception as exc:
            raise MCPManagerError(
                "call_failed",
                server_name,
                f"MCP Server `{server_name}` 工具调用失败（{type(exc).__name__}）。",
            ) from exc

    async def _close_all(self) -> None:
        connections = list(self._connections.values())
        self._connections.clear()
        await asyncio.gather(
            *(connection.exit_stack.aclose() for connection in reversed(connections)),
            return_exceptions=True,
        )


@asynccontextmanager
async def _sdk_session(
    config: MCPServerConfig,
    timeout_seconds: float,
) -> AsyncIterator[ClientSession]:
    read_timeout = timedelta(seconds=timeout_seconds)
    if isinstance(config, StdioMCPServerConfig):
        parameters = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            env={**os.environ, **dict(config.env or {})},
            cwd=Path.cwd(),
        )
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with stdio_client(parameters, errlog=errlog) as (read, write):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=read_timeout,
                ) as session:
                    yield session
        return

    assert isinstance(config, HTTPMCPServerConfig)
    timeout = httpx.Timeout(timeout_seconds, read=timeout_seconds)
    async with httpx.AsyncClient(
        headers=dict(config.headers or {}),
        timeout=timeout,
    ) as client:
        async with streamable_http_client(
            config.url,
            http_client=client,
            terminate_on_close=True,
        ) as (read, write, _get_session_id):
            async with ClientSession(
                read,
                write,
                read_timeout_seconds=read_timeout,
            ) as session:
                yield session
