from __future__ import annotations

from collections.abc import Iterator

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mycode import cli
from mycode.agent.config import AgentRequest
from mycode.agent.events import AgentEvent
from mycode.mcp import MCPDiscoveryWarning, MCPRemoteTool
from mycode.permissions.approval import TerminalApprovalHandler, select_approval_choice
from mycode.permissions.models import ApprovalPrompt, PermissionConfigSet, PermissionLayer
from mycode.types import (
    AppConfig,
    ConfigError,
    ProviderError,
    StdioMCPServerConfig,
    TokenUsage,
    ToolResult,
)
from mycode.context.models import CompactionReport


class FakeAgent:
    requests: list[AgentRequest] = []

    def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
        self.provider = provider

    def run(self, request: AgentRequest, cancellation: object | None = None) -> Iterator[AgentEvent]:
        self.requests.append(request)
        if request.text == "error":
            raise ProviderError("供应商失败")
        yield AgentEvent(type="text_delta", text="你")
        yield AgentEvent(type="text_delta", text="好")
        yield AgentEvent(type="done", stop_reason="completed", message="任务完成。")


class ToolEventAgent:
    def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
        self.provider = provider

    def run(self, request: AgentRequest, cancellation: object | None = None) -> Iterator[AgentEvent]:
        yield AgentEvent(type="progress", iteration=1, max_iterations=8, message="iteration 1/8")
        yield AgentEvent(
            type="tool_call_started",
            tool_call_id="1",
            tool_name="read_file",
            tool_arguments={"path": "a.txt", "content": "hidden"},
        )
        yield AgentEvent(
            type="tool_result",
            tool_call_id="1",
            tool_name="read_file",
            tool_result=ToolResult(ok=True, message="完成", data={}),
        )
        yield AgentEvent(type="text_delta", text="done")
        yield AgentEvent(type="done", stop_reason="completed", message="任务完成。")


class StoppedAgent:
    def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
        self.provider = provider

    def run(self, request: AgentRequest, cancellation: object | None = None) -> Iterator[AgentEvent]:
        yield AgentEvent(type="done", stop_reason="max_iterations", message="达到迭代上限，Agent 已停止。")


class TokenUsageAgent:
    usage = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3)

    def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
        self.provider = provider

    def run(self, request: AgentRequest, cancellation: object | None = None) -> Iterator[AgentEvent]:
        yield AgentEvent(type="token_usage", token_usage=self.usage)
        yield AgentEvent(type="done", stop_reason="completed", message="任务完成。")


class CompactAgent:
    requests: list[AgentRequest] = []
    compact_calls = 0

    def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
        self.provider = provider

    def run(self, request: AgentRequest, cancellation: object | None = None) -> Iterator[AgentEvent]:
        self.requests.append(request)
        yield AgentEvent(type="done", stop_reason="completed", message="任务完成。")

    def compact(self) -> CompactionReport:
        type(self).compact_calls += 1
        return CompactionReport(
            status="success",
            trigger="manual",
            before_tokens=100,
            after_tokens=40,
            budget_tokens=90,
            offloaded_tool_results=2,
            summarized_messages=5,
        )

    def close(self) -> str | None:
        return None


def test_cli_exits_on_exit_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main([]) == 0
    assert "已退出" in capsys.readouterr().out


def test_cli_prints_streaming_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["你好", "exit"])
    prompts: list[str] = []
    FakeAgent.requests = []
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", FakeAgent)

    def fake_read_user_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(inputs)

    monkeypatch.setattr(cli, "read_user_input", fake_read_user_input)

    assert cli.main([]) == 0
    output = capsys.readouterr().out
    assert "● 你好" in output
    assert FakeAgent.requests == [AgentRequest("你好")]
    assert prompts == ["> ", "> "]


def test_parse_agent_request_modes() -> None:
    assert cli.parse_agent_request("/plan 检查项目") == AgentRequest("检查项目", mode="plan")
    assert cli.parse_agent_request("/do 执行计划") == AgentRequest("执行计划", mode="do")
    assert cli.parse_agent_request("普通问题") == AgentRequest("普通问题", mode="default")


def test_cli_compact_is_local_command_and_prints_safe_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inputs = iter(["/compact", "exit"])
    CompactAgent.requests = []
    CompactAgent.compact_calls = 0
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", CompactAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    output = capsys.readouterr().out
    assert CompactAgent.compact_calls == 1
    assert CompactAgent.requests == []
    assert "手动成功 before=100 after=40 budget=90 tools=2 summarized=5" in output


def test_cli_permission_mode_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str | None] = []

    class FakePermissionLoader:
        def __init__(
            self,
            known_tools: set[str],
            *,
            mcp_tool_prefixes: tuple[str, ...] = (),
        ) -> None:
            pass

        def load(self, workspace: object, mode: str | None = None) -> PermissionConfigSet:
            captured.append(mode)
            return PermissionConfigSet(
                PermissionLayer("user"),
                PermissionLayer("project"),
                PermissionLayer("local"),
                mode or "default",
            )

    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "PermissionConfigLoader", FakePermissionLoader)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main(["--permission-mode", "strict"]) == 0
    assert captured == ["strict"]


def test_cli_registers_mcp_tools_and_closes_manager(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_specs: list[str] = []

    class FakeManager:
        instances: list[FakeManager] = []

        def __init__(self, servers: object) -> None:
            self.servers = servers
            self.close_calls = 0
            self.instances.append(self)

        def discover(self) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
            return (
                [
                    MCPRemoteTool(
                        server_name="alpha",
                        remote_name="echo",
                        exposed_name="alpha__echo",
                        description="Echo text",
                        input_schema={"type": "object"},
                    )
                ],
                [MCPDiscoveryWarning("offline", "connect", "连接失败")],
            )

        def close(self) -> None:
            self.close_calls += 1

    class CapturingAgent:
        def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
            registry = kwargs["full_registry"]
            captured_specs.extend(spec.name for spec in registry.tool_specs())

    config = AppConfig(
        "deepseek",
        "m",
        "u",
        "k",
        mcp_servers=(StdioMCPServerConfig("alpha", "stdio", "ignored"),),
    )
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "MCPManager", FakeManager)
    monkeypatch.setattr(cli, "AgentRunner", CapturingAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main([]) == 0
    assert "alpha__echo" in captured_specs
    assert FakeManager.instances[0].close_calls == 1
    assert "[mcp] offline connect 失败：连接失败" in capsys.readouterr().err


def test_cli_cleanup_warning_does_not_block_mcp_close_or_expose_content(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeManager:
        instances: list[FakeManager] = []

        def __init__(self, servers: object) -> None:
            self.close_calls = 0
            self.instances.append(self)

        def discover(self) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
            return [], []

        def close(self) -> None:
            self.close_calls += 1

    class CleanupWarningAgent:
        def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
            pass

        def close(self) -> str:
            return "上下文会话目录清理失败（PermissionError）。"

    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "MCPManager", FakeManager)
    monkeypatch.setattr(cli, "AgentRunner", CleanupWarningAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main([]) == 0
    captured = capsys.readouterr()
    assert "[context] 上下文会话目录清理失败（PermissionError）。" in captured.err
    assert "sensitive body" not in captured.err
    assert FakeManager.instances[0].close_calls == 1


def test_cli_all_mcp_servers_can_fail_without_blocking_local_tools(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_specs: list[str] = []

    class FailedManager:
        def __init__(self, servers: object) -> None:
            self.close_calls = 0

        def discover(self) -> tuple[list[MCPRemoteTool], list[MCPDiscoveryWarning]]:
            return [], [MCPDiscoveryWarning("alpha", "initialize", "初始化失败")]

        def close(self) -> None:
            self.close_calls += 1

    class CapturingAgent:
        def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
            registry = kwargs["full_registry"]
            captured_specs.extend(spec.name for spec in registry.tool_specs())

    config = AppConfig(
        "deepseek",
        "m",
        "u",
        "k",
        mcp_servers=(StdioMCPServerConfig("alpha", "stdio", "ignored"),),
    )
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "MCPManager", FailedManager)
    monkeypatch.setattr(cli, "AgentRunner", CapturingAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main([]) == 0
    assert captured_specs == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "find_files",
        "search_code",
    ]
    assert "[mcp] alpha initialize 失败：初始化失败" in capsys.readouterr().err


def test_terminal_approval_shows_context_and_uses_selector() -> None:
    output: list[str] = []
    handler = TerminalApprovalHandler(selector=lambda: "allow_session", output_func=output.append)

    choice = handler.request(ApprovalPrompt("run_command", "ls -la", "test"))

    assert choice == "allow_session"
    assert any("run_command" in line for line in output)
    assert any("ls -la" in line for line in output)
    assert any("已选择：本会话同意" in line for line in output)


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        ("\r", "deny"),
        ("\x1b[B\r", "allow_once"),
        ("\x1b[B\x1b[B\r", "allow_session"),
        ("\x1b[A\r", "allow_session"),
        ("p\x1b[B\r", "allow_once"),
    ],
)
def test_approval_menu_uses_arrow_keys_and_enter(keys: str, expected: str) -> None:
    with create_pipe_input() as pipe_input:
        pipe_input.send_text(keys)
        choice = select_approval_choice(input=pipe_input, output=DummyOutput(), require_tty=False)

    assert choice == expected


def test_terminal_approval_fails_closed_on_selector_error() -> None:
    def fail() -> str:
        raise EOFError

    handler = TerminalApprovalHandler(selector=fail)
    assert handler.request(ApprovalPrompt("run_command", "ls", "test")) == "deny"


def test_terminal_approval_invalid_choice_fails_closed() -> None:
    output: list[str] = []
    handler = TerminalApprovalHandler(selector=lambda: "invalid", output_func=output.append)  # type: ignore[arg-type]

    assert handler.request(ApprovalPrompt("write_file", "hello.md", "test")) == "deny"
    assert any("已选择：不同意" in line for line in output)


def test_cli_returns_nonzero_on_config_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fail_load(path: object) -> AppConfig:
        raise ConfigError("配置坏了")

    monkeypatch.setattr(cli, "load_config", fail_load)

    assert cli.main([]) == 1
    assert "配置坏了" in capsys.readouterr().err


def test_cli_prints_provider_error_and_continues(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["error", "exit"])
    FakeAgent.requests = []
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", FakeAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert "供应商失败" in capsys.readouterr().err


def test_read_user_input_uses_prompt_toolkit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_prompt(prompt_text: str) -> str:
        calls.append(prompt_text)
        return "我叫什么名字"

    monkeypatch.setattr(cli, "prompt", fake_prompt)

    assert cli.read_user_input("> ") == "我叫什么名字"
    assert calls == ["> "]


def test_cli_prints_agent_tool_events(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["tool", "exit"])
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", ToolEventAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    output = capsys.readouterr().out
    assert "[agent] iteration 1/8" in output
    assert "[tool] read_file 开始：path=a.txt" in output
    assert "[tool] read_file 成功：完成" in output


def test_format_tool_arguments_hides_large_or_sensitive_values() -> None:
    assert cli.format_tool_arguments({"path": "test.md", "content": "secret"}) == "path=test.md"
    assert cli.format_tool_arguments({"path": "x" * 130}) == f"path={'x' * 117}..."


def test_cli_prints_non_completed_stop_reason(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["loop", "exit"])
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", StoppedAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert "[agent] 停止：达到迭代上限，Agent 已停止。" in capsys.readouterr().out


def test_cli_prints_complete_token_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["usage", "exit"])
    TokenUsageAgent.usage = TokenUsage(input_tokens=1, output_tokens=2, total_tokens=3)
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", TokenUsageAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert "[usage] input=1 output=2 total=3" in capsys.readouterr().out


def test_cli_prints_partial_token_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["usage", "exit"])
    TokenUsageAgent.usage = TokenUsage(input_tokens=1, total_tokens=3)
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", TokenUsageAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    output = capsys.readouterr().out
    assert "[usage] input=1 total=3" in output
    assert "output=" not in output


def test_cli_prints_cache_token_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["usage", "exit"])
    TokenUsageAgent.usage = TokenUsage(
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        cache_read_tokens=7,
        cache_creation_tokens=3,
    )
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", TokenUsageAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    assert "[usage] input=10 output=2 total=12 cache_read=7 cache_create=3" in capsys.readouterr().out


def test_cli_prints_cache_unavailable(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["usage", "exit"])
    TokenUsageAgent.usage = TokenUsage(input_tokens=1, cache_unavailable=True)
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", TokenUsageAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    assert "[usage] input=1 cache=unavailable" in capsys.readouterr().out


def test_cli_skips_empty_token_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["usage", "exit"])
    TokenUsageAgent.usage = TokenUsage()
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", TokenUsageAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert "[usage]" not in capsys.readouterr().out
