from __future__ import annotations

from collections.abc import Iterator

import pytest

from mycode import cli
from mycode.agent.config import AgentRequest
from mycode.agent.events import AgentEvent
from mycode.types import AppConfig, ConfigError, ProviderError, TokenUsage, ToolResult


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
        yield AgentEvent(type="tool_call_started", tool_call_id="1", tool_name="read_file")
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
    assert "[tool] read_file 开始" in output
    assert "[tool] read_file 成功：完成" in output


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


def test_cli_skips_empty_token_usage(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["usage", "exit"])
    TokenUsageAgent.usage = TokenUsage()
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "AgentRunner", TokenUsageAgent)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: next(inputs))

    assert cli.main([]) == 0
    assert "[usage]" not in capsys.readouterr().out
