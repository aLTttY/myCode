from __future__ import annotations

import re
from dataclasses import replace

from .interfaces import CommandRegistrationError
from .models import CommandSpec


COMMAND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: list[CommandSpec] = []
        self._lookup: dict[str, CommandSpec] = {}

    def register(self, command: CommandSpec) -> None:
        normalized = _normalized_command(command)
        tokens = (normalized.name, *normalized.aliases)
        if len(tokens) != len(set(tokens)):
            raise CommandRegistrationError(
                f"命令 `/{normalized.name}` 的名称或别名重复。"
            )
        conflicts = [token for token in tokens if token in self._lookup]
        if conflicts:
            token = conflicts[0]
            existing = self._lookup[token]
            raise CommandRegistrationError(
                f"命令标识 `/{token}` 冲突："
                f"`/{existing.name}` 与 `/{normalized.name}`。"
            )

        self._commands.append(normalized)
        for token in tokens:
            self._lookup[token] = normalized

    def resolve(self, name_or_alias: str) -> CommandSpec | None:
        return self._lookup.get(name_or_alias.lower())

    def commands(self, *, include_hidden: bool = False) -> tuple[CommandSpec, ...]:
        if include_hidden:
            return tuple(self._commands)
        return tuple(command for command in self._commands if not command.hidden)

    def completion_candidates(self, fragment: str) -> tuple[CommandSpec, ...]:
        normalized = fragment.lower()
        exact = self._lookup.get(normalized)
        if (
            exact is not None
            and not exact.hidden
            and normalized in exact.aliases
        ):
            return (exact,)
        return tuple(
            command
            for command in self._commands
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
