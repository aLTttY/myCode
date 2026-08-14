from __future__ import annotations

from mycode.commands.interfaces import CommandExecutionError, CommandUI
from mycode.commands.models import CommandInvocation, CommandSpec
from mycode.commands.registry import CommandRegistry

from .models import TeamError
from collections.abc import Callable

from .runtime import TeamRuntime


def team_command(runtime: TeamRuntime | Callable[[], TeamRuntime]) -> CommandSpec:
    def handler(invocation: CommandInvocation, registry: CommandRegistry, ui: CommandUI) -> None:
        del registry
        parts = invocation.arguments.split()
        if not parts:
            raise CommandExecutionError("用法：/team create|resume|switch|status|archive [name]")
        action = parts[0]
        session_id = ui.session_status().session_id
        active_runtime = runtime() if callable(runtime) else runtime
        try:
            if action in {"create", "resume", "switch"}:
                if len(parts) != 2:
                    raise TeamError("invalid_command", f"用法：/team {action} <name>")
                binding = getattr(active_runtime, action)(session_id, parts[1])
                ui.display_message(
                    f"已{ {'create': '创建', 'resume': '恢复', 'switch': '切换'}[action] }小组 `{binding.team_name}`；"
                    f"Coordinator={'on' if binding.coordinator_enabled else 'off'} ({binding.coordinator_reason})。"
                )
                return
            if action == "status" and len(parts) == 1:
                aggregate = active_runtime.status(session_id)
                team = aggregate.team
                ui.display_message(
                    f"team={team.name} status={team.status} revision={team.revision} "
                    f"members={len(team.members)} tasks={len(aggregate.tasks)}"
                )
                return
            if action == "archive" and len(parts) == 1:
                result = active_runtime.archive(session_id)
                ui.display_message(f"小组已保护性归档：{result.path}")
                return
            raise TeamError("invalid_command", "用法：/team create|resume|switch|status|archive [name]")
        except TeamError as exc:
            raise CommandExecutionError(exc.user_message) from exc

    return CommandSpec(
        name="team", aliases=(), description="Create, resume, inspect, switch, or archive a persistent team.",
        usage="/team create|resume|switch|status|archive [name]", command_type="local", handler=handler,
    )
