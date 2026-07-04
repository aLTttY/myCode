from collections.abc import Iterator, Sequence

import pytest

from mycode import cli
from mycode.types import AppConfig, ConfigError, Message, ProviderError, StreamEvent


class FakeSession:
    def __init__(self, provider: object) -> None:
        self.provider = provider

    def send(self, user_text: str) -> Iterator[StreamEvent]:
        if user_text == "error":
            raise ProviderError("供应商失败")
        yield StreamEvent(type="text_delta", text="你")
        yield StreamEvent(type="text_delta", text="好")
        yield StreamEvent(type="message_done")


def test_cli_exits_on_exit_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "ChatSession", FakeSession)
    monkeypatch.setattr(cli, "read_user_input", lambda prompt: "exit")

    assert cli.main([]) == 0
    assert "已退出" in capsys.readouterr().out


def test_cli_prints_streaming_text(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["你好", "exit"])
    prompts: list[str] = []
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "ChatSession", FakeSession)

    def fake_read_user_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(inputs)

    monkeypatch.setattr(cli, "read_user_input", fake_read_user_input)

    assert cli.main([]) == 0
    output = capsys.readouterr().out
    assert "● 你好" in output
    assert prompts == ["> ", "> "]


def test_cli_returns_nonzero_on_config_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fail_load(path: object) -> AppConfig:
        raise ConfigError("配置坏了")

    monkeypatch.setattr(cli, "load_config", fail_load)

    assert cli.main([]) == 1
    assert "配置坏了" in capsys.readouterr().err


def test_cli_prints_provider_error_and_continues(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = iter(["error", "exit"])
    monkeypatch.setattr(cli, "load_config", lambda path: AppConfig("deepseek", "m", "u", "k"))
    monkeypatch.setattr(cli, "create_provider", lambda config: object())
    monkeypatch.setattr(cli, "ChatSession", FakeSession)
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
