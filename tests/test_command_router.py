from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mycode.commands.interfaces import CommandExecutionError
from mycode.commands.models import CommandInvocation, CommandSpec
from mycode.commands.registry import CommandRegistry
from mycode.commands.router import CommandDispatcher, InputRouter


@dataclass
class RecordingUI:
    messages: list[tuple[str, bool]] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)

    def display_message(self, text: str, *, error: bool = False) -> None:
        self.messages.append((text, error))

    def send_user_message(self, text: str, *, mode_override=None) -> None:
        self.sent.append(text)


def _registry(handler=None) -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        CommandSpec(
            name="status",
            aliases=("st",),
            description="状态",
            usage="/status",
            command_type="local",
            handler=handler,
        )
    )
    return registry


@pytest.mark.parametrize("raw", ["", " ", "\t\n"])
def test_router_returns_empty_without_side_effects(raw: str) -> None:
    route = InputRouter(_registry()).route(raw)

    assert route.kind == "empty"
    assert route.invocation is None


@pytest.mark.parametrize("raw", ["exit", " EXIT ", "Quit", "退出"])
def test_router_recognizes_exit_case_insensitively(raw: str) -> None:
    assert InputRouter(_registry()).route(raw).kind == "exit"


def test_router_preserves_plain_message_after_outer_strip() -> None:
    route = InputRouter(_registry()).route("  你好，世界  ")

    assert route.kind == "plain"
    assert route.text == "你好，世界"


def test_router_resolves_case_insensitive_name_and_alias() -> None:
    router = InputRouter(_registry())

    by_name = router.route("/STATUS")
    by_alias = router.route("/St")

    assert by_name.kind == "command"
    assert by_name.invocation is not None
    assert by_name.invocation.command.name == "status"
    assert by_name.invocation.entered_name == "STATUS"
    assert by_alias.invocation is not None
    assert by_alias.invocation.command.name == "status"


def test_router_splits_only_at_first_whitespace() -> None:
    route = InputRouter(_registry()).route(" /status   one   two  ")

    assert route.invocation is not None
    assert route.invocation.arguments == "one   two"


def test_router_rejects_unknown_command_without_echoing_arguments() -> None:
    route = InputRouter(_registry()).route("/missing secret argument")

    assert route.kind == "error"
    assert "/help" in route.message
    assert "secret argument" not in route.message


def test_router_rejects_bare_slash_with_help_hint() -> None:
    route = InputRouter(_registry()).route("/  ")

    assert route.kind == "error"
    assert "/help" in route.message


def test_dispatcher_calls_handler_once() -> None:
    calls: list[CommandInvocation] = []

    def handler(invocation, registry, ui) -> None:
        calls.append(invocation)

    registry = _registry(handler)
    invocation = InputRouter(registry).route("/status").invocation
    assert invocation is not None

    CommandDispatcher(registry).dispatch(invocation, RecordingUI())

    assert calls == [invocation]


def test_dispatcher_reports_missing_handler_without_sending_to_agent() -> None:
    registry = _registry()
    command = registry.resolve("status")
    assert command is not None
    ui = RecordingUI()

    CommandDispatcher(registry).dispatch(
        CommandInvocation(command, "status", ""), ui
    )

    assert ui.messages == [
        ("命令 `/status` 暂不可执行；使用 /help 查看帮助。", True)
    ]
    assert ui.sent == []


def test_dispatcher_reports_safe_command_execution_error() -> None:
    def handler(invocation, registry, ui) -> None:
        raise CommandExecutionError("安全提示")

    registry = _registry(handler)
    command = registry.resolve("status")
    assert command is not None
    ui = RecordingUI()

    CommandDispatcher(registry).dispatch(
        CommandInvocation(command, "status", ""), ui
    )

    assert ui.messages == [("安全提示", True)]
    assert ui.sent == []


def test_dispatcher_hides_unexpected_exception_message() -> None:
    def handler(invocation, registry, ui) -> None:
        raise RuntimeError("api-key-is-secret")

    registry = _registry(handler)
    command = registry.resolve("status")
    assert command is not None
    ui = RecordingUI()

    CommandDispatcher(registry).dispatch(
        CommandInvocation(command, "status", ""), ui
    )

    assert ui.messages == [("命令 `/status` 执行失败（RuntimeError）。", True)]
    assert "api-key" not in ui.messages[0][0]


@pytest.mark.parametrize("error", [KeyboardInterrupt(), EOFError(), SystemExit()])
def test_dispatcher_does_not_swallow_control_flow(error: BaseException) -> None:
    def handler(invocation, registry, ui) -> None:
        raise error

    registry = _registry(handler)
    command = registry.resolve("status")
    assert command is not None

    with pytest.raises(type(error)):
        CommandDispatcher(registry).dispatch(
            CommandInvocation(command, "status", ""), RecordingUI()
        )
