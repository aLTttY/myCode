from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mycode import cli
from mycode.agent.config import AgentRequest
from mycode.agent.events import AgentEvent
from mycode.commands import CommandRegistrationError
from mycode.hooks.models import HookRule, HookSnapshot, PromptAction
from mycode.mcp import MCPDiscoveryWarning, MCPRemoteTool
from mycode.permissions.approval import TerminalApprovalHandler, select_approval_choice
from mycode.permissions.models import ApprovalPrompt, PermissionConfigSet, PermissionLayer
from mycode.types import (
    AppConfig,
    ConfigError,
    ProviderError,
    StdioMCPServerConfig,
    Message,
    TokenUsage,
    ToolResult,
)
from mycode.context.models import CompactionReport, ContextStatus
from mycode.sessions import SessionJournal


@pytest.fixture(autouse=True)
def isolate_cli_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


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

    def compact(self, mode="default") -> CompactionReport:
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


def test_cli_new_is_local_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["/new", "exit"])

    class NewAgent(FakeAgent):
        requests = []

        def new_session(self):
            return "20260721-120000-abcd", ()

    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", NewAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert NewAgent.requests == []
    assert "新会话 20260721-120000-abcd" in capsys.readouterr().out


def test_cli_default_restores_but_new_flag_skips_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.append(Message(role="user", content="restore me"))
    journal.append(Message(role="assistant", content="saved"))
    journal.close()
    captured: list[tuple[Message, ...]] = []

    class CapturingRestoreAgent:
        def __init__(self, provider, *args, **kwargs):
            captured.append(tuple(kwargs["restored_messages"]))

        def close(self):
            return None

    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", CapturingRestoreAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main([]) == 0
    assert [message.content for message in captured[-1]] == ["restore me", "saved"]
    assert cli.main(["--new"]) == 0
    assert captured[-1] == ()


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
        "read_git_changes",
        "Agent",
        "Task",
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


class StatefulAgent:
    instances: list[StatefulAgent] = []

    def __init__(self, provider: object, *args: object, **kwargs: object) -> None:
        self.provider = provider
        self.requests: list[AgentRequest] = []
        self.skill_requests: list[tuple[str, str, str]] = []
        self.context_status_calls: list[str] = []
        self.session_journal = kwargs["session_journal"]
        self.new_calls = 0
        self.instances.append(self)

    def run(
        self,
        request: AgentRequest,
        cancellation: object | None = None,
    ) -> Iterator[AgentEvent]:
        self.requests.append(request)
        yield AgentEvent(
            type="token_usage",
            token_usage=TokenUsage(input_tokens=11, output_tokens=7, total_tokens=18),
        )
        yield AgentEvent(type="done", stop_reason="completed", message="任务完成。")

    def invoke_skill(self, name, input_text, *, mode="default", cancellation=None):
        self.skill_requests.append((name, input_text, mode))
        yield AgentEvent(type="done", stop_reason="completed", message="Skill 执行完成。")

    def context_status(self, mode="default") -> ContextStatus:
        self.context_status_calls.append(mode)
        return ContextStatus(120, 1_000, len(self.requests) * 2, False, False)

    def compact(self, mode="default") -> CompactionReport:
        return CompactionReport("not_needed", "manual", 120, 120, 900)

    def new_session(self):
        self.new_calls += 1
        self.session_journal = SimpleNamespace(session_id="20260810-120000-abcd")
        return self.session_journal.session_id, ()

    def take_memory_notices(self):
        return ()

    def close(self):
        return None


class CapturingPromptSession:
    instances: list[CapturingPromptSession] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.initial_toolbar = kwargs["bottom_toolbar"]()
        self.toolbar_values: list[str] = []
        self.app = SimpleNamespace(is_running=True, invalidate=self._invalidate)
        self.instances.append(self)

    def _invalidate(self) -> None:
        toolbar = self.kwargs["bottom_toolbar"]
        self.toolbar_values.append(toolbar())


class CountingMCPManager:
    instances: list[CountingMCPManager] = []

    def __init__(self, servers: object) -> None:
        self.discover_calls = 0
        self.close_calls = 0
        self.instances.append(self)

    def discover(self):
        self.discover_calls += 1
        return [], []

    def close(self) -> None:
        self.close_calls += 1


def _prepare_stateful_cli(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    providers: list[object] = []
    StatefulAgent.instances = []
    CapturingPromptSession.instances = []
    CountingMCPManager.instances = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda path: AppConfig("deepseek", "state-model", "sensitive-url", "secret-key"),
    )

    def create(config: object) -> object:
        provider = object()
        providers.append(provider)
        return provider

    monkeypatch.setattr(cli, "create_provider", create)
    monkeypatch.setattr(cli, "AgentRunner", StatefulAgent)
    monkeypatch.setattr(cli, "PromptSession", CapturingPromptSession)
    monkeypatch.setattr(cli, "MCPManager", CountingMCPManager)
    return providers


def test_command_registration_failure_happens_before_configuration_or_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def fail_registry():
        raise CommandRegistrationError("status 与 st 冲突")

    monkeypatch.setattr(cli, "create_default_command_registry", fail_registry)
    monkeypatch.setattr(cli, "load_config", lambda path: calls.append("config"))
    monkeypatch.setattr(cli, "create_provider", lambda config: calls.append("provider"))

    assert cli.main([]) == 1
    assert calls == []
    assert "命令注册错误" in capsys.readouterr().err


def test_slash_command_end_to_end_routes_only_plain_and_review_to_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    providers = _prepare_stateful_cli(monkeypatch)
    inputs = iter(
        [
            "/p",
            "检查当前实现",
            "/status",
            "/review",
            "/d",
            "/clear",
            "/help status",
            "exit",
        ]
    )
    clear_calls: list[bool] = []
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))
    monkeypatch.setattr(cli, "clear", lambda: clear_calls.append(True))

    assert cli.main([]) == 0

    agent = StatefulAgent.instances[0]
    assert agent.requests == [
        AgentRequest("检查当前实现", mode="plan"),
    ]
    assert agent.skill_requests == [("review", "", "plan")]
    assert CapturingPromptSession.instances[0].toolbar_values == [
        "[PLAN]",
        "[DEFAULT]",
    ]
    assert CapturingPromptSession.instances[0].initial_toolbar == "[DEFAULT]"
    assert len(CapturingPromptSession.instances) == 1
    session_kwargs = CapturingPromptSession.instances[0].kwargs
    assert session_kwargs["complete_while_typing"] is False
    assert session_kwargs["bottom_toolbar"]() == "[DEFAULT]"
    assert clear_calls == [True]
    assert len(providers) == 2
    assert CountingMCPManager.instances[0].discover_calls == 1
    assert CountingMCPManager.instances[0].close_calls == 1

    captured = capsys.readouterr()
    assert "mode=plan provider=deepseek model=state-model" in captured.out
    assert "[usage] input=11 output=7 total=18" in captured.out
    assert "命令：/status" in captured.out
    assert "sensitive-url" not in captured.out
    assert "secret-key" not in captured.out


def test_local_status_commands_do_not_send_agent_requests_or_repeat_discovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    providers = _prepare_stateful_cli(monkeypatch)
    inputs = iter(["/session", "/memory", "/permission", "/status", "exit"])
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    agent = StatefulAgent.instances[0]
    assert agent.requests == []
    assert len(providers) == 2
    assert CountingMCPManager.instances[0].discover_calls == 1
    output = capsys.readouterr().out
    assert "origin=new" in output
    assert "worker=idle pending=0" in output
    assert "priority=session > local > project > user" in output
    assert "source=default" in output
    assert "[usage] unavailable" in output


def test_clear_preserves_mode_session_and_last_usage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_stateful_cli(monkeypatch)
    clear_calls: list[bool] = []
    inputs = iter(["/plan", "建立状态", "/clear", "/status", "exit"])
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))
    monkeypatch.setattr(cli, "clear", lambda: clear_calls.append(True))

    assert cli.main([]) == 0

    assert clear_calls == [True]
    output = capsys.readouterr().out
    assert "mode=plan provider=deepseek model=state-model" in output
    assert "[usage] input=11 output=7 total=18" in output
    assert "origin=new" in output


def test_review_is_isolated_skill_and_does_not_change_default_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_stateful_cli(monkeypatch)
    inputs = iter(["/review", "继续执行", "exit"])
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    assert StatefulAgent.instances[0].requests == [
        AgentRequest("继续执行", mode="default"),
    ]
    assert StatefulAgent.instances[0].skill_requests == [("review", "", "default")]
    assert CapturingPromptSession.instances[0].kwargs["bottom_toolbar"]() == "[DEFAULT]"


def test_new_session_preserves_plan_mode_and_clears_last_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _prepare_stateful_cli(monkeypatch)
    inputs = iter(["/plan", "建立上下文", "/new", "/status", "exit"])
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    agent = StatefulAgent.instances[0]
    assert agent.requests == [AgentRequest("建立上下文", mode="plan")]
    assert agent.new_calls == 1
    assert CapturingPromptSession.instances[0].kwargs["bottom_toolbar"]() == "[PLAN]"
    output = capsys.readouterr().out
    assert "session=20260810-120000-abcd origin=new" in output
    assert "[usage] unavailable" in output


@pytest.mark.parametrize(
    ("failure", "expected"),
    [(KeyboardInterrupt(), "已退出"), (EOFError(), "")],
)
def test_cli_input_control_flow_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
    expected: str,
) -> None:
    _prepare_stateful_cli(monkeypatch)

    def fail(prompt: str) -> str:
        raise failure

    monkeypatch.setattr(cli, "read_user_input", fail)

    assert cli.main([]) == 0
    assert expected in capsys.readouterr().out


def test_agent_keyboard_interrupt_cancels_only_current_turn(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class InterruptingAgent(StatefulAgent):
        def run(self, request, cancellation=None):
            self.requests.append(request)
            if request.text == "interrupt":
                raise KeyboardInterrupt
            yield AgentEvent(type="done", stop_reason="completed", message="任务完成。")

    _prepare_stateful_cli(monkeypatch)
    InterruptingAgent.instances = []
    monkeypatch.setattr(cli, "AgentRunner", InterruptingAgent)
    inputs = iter(["interrupt", "继续", "exit"])
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert [request.text for request in InterruptingAgent.instances[0].requests] == [
        "interrupt",
        "继续",
    ]
    assert "已取消" in capsys.readouterr().out


def test_invalid_hook_config_stops_before_provider_and_mcp_initialization(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    hook_path = tmp_path / ".mycode/hooks.yaml"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text(
        "hooks:\n  - event: session_end\n    action: {type: prompt, content: invalid}\n",
        encoding="utf-8",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda path: AppConfig("deepseek", "m", "u", "k"),
    )
    monkeypatch.setattr(cli, "create_provider", lambda config: calls.append("provider"))

    class MustNotCreateMCP:
        def __init__(self, servers):
            calls.append("mcp")

    monkeypatch.setattr(cli, "MCPManager", MustNotCreateMCP)

    assert cli.main([]) == 1
    assert calls == []
    assert "Hook 配置" in capsys.readouterr().err


def test_cli_hook_session_lifecycle_includes_new_switch_and_cleanup_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple] = []
    snapshot = HookSnapshot(
        (
            HookRule(
                "project:1",
                "project",
                Path("/workspace/.mycode/hooks.yaml"),
                1,
                "session_start",
                None,
                PromptAction("hello"),
            ),
        )
    )

    class FakeHookLoader:
        def load(self, workspace_root):
            return snapshot

    class FakeHookRuntime:
        def __init__(self, snapshot, event_factory, action_executor, diagnostic_sink):
            self.closed = False

        def begin_session(self, session_id, origin):
            events.append(("begin", session_id, origin))

        def end_session(self, reason):
            events.append(("end", reason))

        def close(self):
            if self.closed:
                return
            self.closed = True
            events.append(("hook_close",))

    class LifecycleAgent(StatefulAgent):
        def __init__(self, provider, *args, **kwargs):
            super().__init__(provider, *args, **kwargs)
            self.hook_runtime = kwargs["hook_runtime"]

        def new_session(self):
            events.append(("agent_new",))
            return super().new_session()

        def close(self):
            events.append(("agent_close",))
            return None

    _prepare_stateful_cli(monkeypatch)
    LifecycleAgent.instances = []
    monkeypatch.setattr(cli, "AgentRunner", LifecycleAgent)
    monkeypatch.setattr(cli, "HookConfigLoader", FakeHookLoader)
    monkeypatch.setattr(cli, "HookRuntime", FakeHookRuntime)
    inputs = iter(["/new", "exit"])
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0

    assert events[0][0] == "begin" and events[0][2] == "new"
    assert events[1:] == [
        ("end", "switched"),
        ("agent_new",),
        ("begin", "20260810-120000-abcd", "new"),
        ("end", "exit"),
        ("agent_close",),
        ("hook_close",),
    ]


def test_render_keyboard_interrupt_closes_event_iterator() -> None:
    closed: list[bool] = []

    def interrupted():
        try:
            raise KeyboardInterrupt
            yield AgentEvent(type="done")
        finally:
            closed.append(True)

    cancellation = cli.CancellationToken()
    cli._render_agent_events(object(), interrupted(), cancellation, lambda usage: None)

    assert cancellation.is_cancelled()
    assert closed == [True]


def test_team_worker_subcommand_is_dispatched_before_normal_cli(monkeypatch) -> None:
    monkeypatch.setattr(cli, "worker_main", lambda argv: 7 if list(argv) == ["--team", "alpha"] else 9)
    assert cli.main(["team-worker", "--team", "alpha"]) == 7
