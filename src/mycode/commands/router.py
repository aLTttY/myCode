from __future__ import annotations

from .interfaces import CommandExecutionError, CommandUI
from .models import CommandInvocation, InputRoute
from .registry import CommandRegistry


EXIT_COMMANDS = frozenset({"exit", "quit", "退出"})


class InputRouter:
    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def route(self, raw_text: str) -> InputRoute:
        text = raw_text.strip()
        if not text:
            return InputRoute(kind="empty")
        if text.lower() in EXIT_COMMANDS:
            return InputRoute(kind="exit")
        if not text.startswith("/"):
            return InputRoute(kind="plain", text=text)

        command_text = text[1:]
        parts = command_text.split(maxsplit=1)
        if not parts:
            return InputRoute(
                kind="error",
                message="请输入命令名；使用 /help 查看可用命令。",
            )

        entered_name = parts[0]
        command = self._registry.resolve(entered_name)
        if command is None:
            return InputRoute(
                kind="error",
                message=f"未知命令 `/{entered_name}`；使用 /help 查看可用命令。",
            )

        arguments = parts[1].strip() if len(parts) == 2 else ""
        return InputRoute(
            kind="command",
            invocation=CommandInvocation(
                command=command,
                entered_name=entered_name,
                arguments=arguments,
            ),
        )


class CommandDispatcher:
    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def dispatch(self, invocation: CommandInvocation, ui: CommandUI) -> None:
        command = invocation.command
        if command.handler is None:
            ui.display_message(
                f"命令 `/{command.name}` 暂不可执行；使用 /help 查看帮助。",
                error=True,
            )
            return

        try:
            command.handler(invocation, self._registry, ui)
        except (KeyboardInterrupt, EOFError, SystemExit):
            raise
        except CommandExecutionError as exc:
            ui.display_message(exc.user_message, error=True)
        except Exception as exc:
            ui.display_message(
                f"命令 `/{command.name}` 执行失败（{type(exc).__name__}）。",
                error=True,
            )
