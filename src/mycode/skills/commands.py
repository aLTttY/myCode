from __future__ import annotations

from mycode.commands.models import CommandInvocation, CommandSpec
from mycode.commands.registry import CommandRegistry

from .models import SkillDefinition, SkillSnapshot


def commands_from_snapshot(snapshot: SkillSnapshot) -> tuple[CommandSpec, ...]:
    return tuple(
        _command_for(definition)
        for definition in sorted(snapshot.definitions.values(), key=lambda item: item.name)
    )


def _command_for(definition: SkillDefinition) -> CommandSpec:
    aliases = ("rev",) if definition.name == "review" else ()

    def invoke(invocation: CommandInvocation, registry: CommandRegistry, ui) -> None:
        ui.invoke_skill(definition.name, invocation.arguments)

    return CommandSpec(
        name=definition.name,
        aliases=aliases,
        description=definition.description,
        usage=f"/{definition.name} [输入]",
        command_type="prompt",
        argument_hint="[输入]",
        handler=invoke,
        origin="skill",
        skill_source=definition.source,
        skill_mode=definition.mode,
        skill_history=definition.history,
        skill_model=definition.model or "",
    )
