from __future__ import annotations

import re
from dataclasses import replace
from threading import RLock
from collections.abc import Sequence

from .interfaces import CommandRegistrationError
from .models import CommandSpec


COMMAND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class CommandRegistry:
    def __init__(self) -> None:
        self._fixed_commands: list[CommandSpec] = []
        self._dynamic_commands: list[CommandSpec] = []
        self._lookup: dict[str, CommandSpec] = {}
        self._lock = RLock()

    def register(self, command: CommandSpec) -> None:
        normalized = _normalized_command(command)
        with self._lock:
            commands = [*self._fixed_commands, normalized, *self._dynamic_commands]
            lookup = _build_lookup(commands)
            self._fixed_commands.append(normalized)
            self._lookup = lookup

    def replace_dynamic(self, commands: Sequence[CommandSpec]) -> None:
        normalized = [_normalized_command(command) for command in commands]
        with self._lock:
            lookup = _build_lookup([*self._fixed_commands, *normalized])
            self._dynamic_commands = normalized
            self._lookup = lookup

    def resolve(self, name_or_alias: str) -> CommandSpec | None:
        with self._lock:
            return self._lookup.get(name_or_alias.lower())

    def commands(self, *, include_hidden: bool = False) -> tuple[CommandSpec, ...]:
        with self._lock:
            commands = tuple((*self._fixed_commands, *self._dynamic_commands))
        if include_hidden:
            return commands
        return tuple(command for command in commands if not command.hidden)

    def completion_candidates(self, fragment: str) -> tuple[CommandSpec, ...]:
        normalized = fragment.lower()
        with self._lock:
            exact = self._lookup.get(normalized)
            commands = tuple((*self._fixed_commands, *self._dynamic_commands))
        if (
            exact is not None
            and not exact.hidden
            and normalized in exact.aliases
        ):
            return (exact,)
        return tuple(
            command
            for command in commands
            if not command.hidden and command.name.startswith(normalized)
        )


def _normalized_command(command: CommandSpec) -> CommandSpec:
    name = command.name.lower()
    aliases = tuple(alias.lower() for alias in command.aliases)
    if COMMAND_NAME_PATTERN.fullmatch(name) is None:
        raise CommandRegistrationError(
            f"命令名 `{command.name}` 非法；只能使用小写字母开头的字母、数字、下划线或连字符。"
        )
    for alias in aliases:
        if alias != "?" and COMMAND_NAME_PATTERN.fullmatch(alias) is None:
            raise CommandRegistrationError(
                f"命令 `/{name}` 的别名 `{alias}` 非法。"
            )
    return replace(command, name=name, aliases=aliases)


def _build_lookup(commands: Sequence[CommandSpec]) -> dict[str, CommandSpec]:
    lookup: dict[str, CommandSpec] = {}
    for command in commands:
        tokens = (command.name, *command.aliases)
        if len(tokens) != len(set(tokens)):
            raise CommandRegistrationError(
                f"命令 `/{command.name}` 的名称或别名重复。"
            )
        for token in tokens:
            existing = lookup.get(token)
            if existing is not None:
                raise CommandRegistrationError(
                    f"命令标识 `/{token}` 冲突："
                    f"`/{existing.name}` 与 `/{command.name}`。"
                )
            lookup[token] = command
    return lookup
