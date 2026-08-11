from __future__ import annotations

import pytest

from mycode.commands import (
    CommandRegistrationError,
    CommandRegistry,
    CommandSpec,
)


def spec(
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    hidden: bool = False,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        aliases=aliases,
        description=f"{name} description",
        usage=f"/{name}",
        command_type="local",
        hidden=hidden,
    )


def test_registry_normalizes_and_resolves_names_and_aliases() -> None:
    registry = CommandRegistry()
    registry.register(spec("Help", aliases=("H", "?")))

    command = registry.resolve("HELP")

    assert command is not None
    assert command.name == "help"
    assert command.aliases == ("h", "?")
    assert registry.resolve("h") is command
    assert registry.resolve("?") is command


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (spec("help"), spec("HELP")),
        (spec("help", aliases=("h",)), spec("h")),
        (spec("help"), spec("status", aliases=("HELP",))),
        (spec("help", aliases=("h",)), spec("status", aliases=("H",))),
    ],
)
def test_registry_rejects_all_cross_command_conflicts(
    first: CommandSpec,
    second: CommandSpec,
) -> None:
    registry = CommandRegistry()
    registry.register(first)

    with pytest.raises(CommandRegistrationError, match="冲突"):
        registry.register(second)

    assert registry.commands(include_hidden=True) == (registry.resolve(first.name),)


@pytest.mark.parametrize(
    "command",
    [
        spec("help", aliases=("help",)),
        spec("help", aliases=("h", "H")),
    ],
)
def test_registry_rejects_duplicates_inside_one_command(command: CommandSpec) -> None:
    registry = CommandRegistry()

    with pytest.raises(CommandRegistrationError, match="重复"):
        registry.register(command)

    assert registry.commands(include_hidden=True) == ()


@pytest.mark.parametrize(
    "command",
    [
        spec("?"),
        spec("two words"),
        spec("/help"),
        spec("9help"),
        spec("help", aliases=("two words",)),
        spec("help", aliases=("/h",)),
    ],
)
def test_registry_rejects_invalid_tokens_atomically(command: CommandSpec) -> None:
    registry = CommandRegistry()

    with pytest.raises(CommandRegistrationError, match="非法"):
        registry.register(command)

    assert registry.commands(include_hidden=True) == ()


def test_registry_filters_hidden_commands_but_resolves_them() -> None:
    registry = CommandRegistry()
    registry.register(spec("help"))
    registry.register(spec("new", hidden=True))

    assert [command.name for command in registry.commands()] == ["help"]
    assert [command.name for command in registry.commands(include_hidden=True)] == [
        "help",
        "new",
    ]
    assert registry.resolve("new") is not None


def test_completion_candidates_preserve_order_and_prefer_exact_alias() -> None:
    registry = CommandRegistry()
    registry.register(spec("plan", aliases=("p",)))
    registry.register(spec("permission", aliases=("perm",)))
    registry.register(spec("status", aliases=("st",)))
    registry.register(spec("new", hidden=True))

    assert [item.name for item in registry.completion_candidates("p")] == ["plan"]
    assert [item.name for item in registry.completion_candidates("s")] == ["status"]
    assert registry.completion_candidates("n") == ()


def test_command_handler_is_optional_metadata() -> None:
    registry = CommandRegistry()
    registry.register(spec("help"))

    assert registry.resolve("help").handler is None  # type: ignore[union-attr]


def test_replace_dynamic_is_atomic_and_preserves_fixed_commands() -> None:
    registry = CommandRegistry()
    registry.register(spec("help"))
    registry.replace_dynamic((spec("commit"), spec("review", aliases=("rev",))))

    assert [item.name for item in registry.commands()] == ["help", "commit", "review"]
    assert registry.resolve("rev").name == "review"  # type: ignore[union-attr]

    with pytest.raises(CommandRegistrationError, match="冲突"):
        registry.replace_dynamic((spec("help"),))

    assert [item.name for item in registry.commands()] == ["help", "commit", "review"]
