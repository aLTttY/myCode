from __future__ import annotations

from mycode.context.models import CompactionReport, ContextStatus
from mycode.types import TokenUsage

from .interfaces import CommandExecutionError, CommandUI
from .models import (
    ApplicationStatus,
    CommandInvocation,
    CommandSpec,
    MemoryStatus,
    PermissionStatus,
    SessionStatus,
    TokenStatus,
    AgentTaskSummary,
)
from .registry import CommandRegistry


def create_default_command_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for command in _builtin_commands():
        registry.register(command)
    return registry


def _builtin_commands() -> tuple[CommandSpec, ...]:
    return (
        CommandSpec(
            name="help",
            aliases=("h", "?"),
            description="显示命令总览或单条命令帮助",
            usage="/help [命令]",
            command_type="local",
            argument_hint="[命令]",
            handler=_handle_help,
        ),
        CommandSpec(
            name="compact",
            aliases=("cmp",),
            description="压缩当前会话上下文",
            usage="/compact",
            command_type="local",
            handler=_handle_compact,
        ),
        CommandSpec(
            name="clear",
            aliases=("cls",),
            description="清除终端显示内容",
            usage="/clear",
            command_type="ui",
            handler=_handle_clear,
        ),
        CommandSpec(
            name="plan",
            aliases=("p",),
            description="进入只读计划模式",
            usage="/plan",
            command_type="ui",
            handler=_handle_plan,
        ),
        CommandSpec(
            name="do",
            aliases=("d",),
            description="返回默认执行模式",
            usage="/do",
            command_type="ui",
            handler=_handle_do,
        ),
        CommandSpec(
            name="session",
            aliases=("sess",),
            description="显示当前会话概况",
            usage="/session",
            command_type="local",
            handler=_handle_session,
        ),
        CommandSpec(
            name="memory",
            aliases=("mem",),
            description="显示记忆索引与后台状态",
            usage="/memory",
            command_type="local",
            handler=_handle_memory,
        ),
        CommandSpec(
            name="permission",
            aliases=("perm",),
            description="显示当前权限配置概况",
            usage="/permission",
            command_type="local",
            handler=_handle_permission,
        ),
        CommandSpec(
            name="status",
            aliases=("st",),
            description="汇总 Agent 与应用状态",
            usage="/status",
            command_type="local",
            handler=_handle_status,
        ),
        CommandSpec(
            name="new",
            aliases=(),
            description="关闭当前会话并创建新会话",
            usage="/new",
            command_type="local",
            hidden=True,
            handler=_handle_new,
        ),
        CommandSpec(
            name="tasks",
            aliases=(),
            description="显示当前会话的子 Agent 任务",
            usage="/tasks",
            command_type="local",
            handler=_handle_tasks,
        ),
    )


def _require_no_arguments(invocation: CommandInvocation) -> None:
    if invocation.arguments:
        raise CommandExecutionError(
            f"命令 `/{invocation.command.name}` 不接受参数。"
            f"正确用法：{invocation.command.usage}；使用 /help 查看帮助。"
        )


def _handle_help(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    arguments = invocation.arguments
    if not arguments:
        rows = ["可用命令："]
        for command in registry.commands():
            hint = f" {command.argument_hint}" if command.argument_hint else ""
            rows.append(f"  /{command.name}{hint} — {command.description}")
        rows.append("输入 /help <命令> 查看详情。")
        ui.display_message("\n".join(rows))
        return

    if any(character.isspace() for character in arguments):
        raise CommandExecutionError(
            "命令 `/help` 最多接受一个命令名。"
            "正确用法：/help [命令]；使用 /help 查看帮助。"
        )
    target_name = arguments.removeprefix("/")
    target = registry.resolve(target_name)
    if target is None:
        raise CommandExecutionError(
            f"没有名为 `/{target_name}` 的命令；使用 /help 查看可用命令。"
        )
    aliases = ", ".join(f"/{alias}" for alias in target.aliases) or "无"
    argument_hint = target.argument_hint or "无"
    rows = [
        f"命令：/{target.name}",
        f"别名：{aliases}",
        f"类型：{target.command_type}",
        f"描述：{target.description}",
        f"用法：{target.usage}",
        f"参数提示：{argument_hint}",
    ]
    if target.origin == "skill":
        rows.extend(
            (
                f"Skill 来源：{target.skill_source}",
                f"Skill 模式：{target.skill_mode}",
                f"历史轮数：{target.skill_history if target.skill_history is not None else '共享上下文'}",
                f"指定模型：{target.skill_model or '当前模型'}",
            )
        )
    ui.display_message("\n".join(rows))


def _handle_compact(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.display_message(f"[context] {format_compaction_report(ui.compact_context())}")


def _handle_clear(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.clear_screen()


def _handle_plan(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.switch_mode("plan")
    ui.display_message("已切换到计划模式。")
    ui.refresh_status()


def _handle_do(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.switch_mode("default")
    ui.display_message("已切换到默认执行模式。")
    ui.refresh_status()


def _handle_session(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.display_message(format_session_status(ui.session_status()))


def _handle_memory(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.display_message(format_memory_status(ui.memory_status()))


def _handle_permission(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.display_message(format_permission_status(ui.permission_status()))


def _handle_status(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.display_message(format_application_status(ui.application_status()))


def _handle_new(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.new_session()


def _handle_tasks(
    invocation: CommandInvocation,
    registry: CommandRegistry,
    ui: CommandUI,
) -> None:
    _require_no_arguments(invocation)
    ui.display_message(format_agent_tasks(ui.task_statuses()))


def format_agent_tasks(tasks: tuple[AgentTaskSummary, ...]) -> str:
    if not tasks:
        return "当前会话没有子 Agent 任务。"
    rows = ["子 Agent 任务："]
    for task in tasks:
        role = task.role or "-"
        usage = format_token_usage(task.token_usage)
        suffix = f" failure={task.failure_reason}" if task.failure_reason else ""
        rows.append(
            f"  {task.task_id} type={task.kind} role={role} "
            f"status={task.status} delivery={task.delivery_mode} usage={usage}{suffix}"
        )
    return "\n".join(rows)


def format_token_usage(usage: TokenUsage | None) -> str:
    if usage is None:
        return "unavailable"
    parts: list[str] = []
    if usage.input_tokens is not None:
        parts.append(f"input={usage.input_tokens}")
    if usage.output_tokens is not None:
        parts.append(f"output={usage.output_tokens}")
    if usage.total_tokens is not None:
        parts.append(f"total={usage.total_tokens}")
    if usage.cache_read_tokens is not None:
        parts.append(f"cache_read={usage.cache_read_tokens}")
    if usage.cache_creation_tokens is not None:
        parts.append(f"cache_create={usage.cache_creation_tokens}")
    if (
        usage.cache_unavailable
        and usage.cache_read_tokens is None
        and usage.cache_creation_tokens is None
    ):
        parts.append("cache=unavailable")
    return " ".join(parts) or "unavailable"


def format_context_status(status: ContextStatus) -> str:
    return (
        f"tokens={status.estimated_tokens}/{status.window_tokens} "
        f"messages={status.message_count} "
        f"summary={'yes' if status.has_summary else 'no'} "
        f"auto_tripped={'yes' if status.automatic_summary_tripped else 'no'}"
    )


def format_compaction_report(report: CompactionReport) -> str:
    status_labels = {
        "success": "成功",
        "failed": "失败",
        "not_needed": "无需压缩",
        "tripped": "已熔断",
    }
    trigger = "自动" if report.trigger == "automatic" else "手动"
    parts = [
        f"{trigger}{status_labels[report.status]}",
        f"before={report.before_tokens}",
        f"after={report.after_tokens}",
        f"budget={report.budget_tokens}",
    ]
    if report.offloaded_tool_results:
        parts.append(f"tools={report.offloaded_tool_results}")
    if report.offloaded_user_messages:
        parts.append(f"users={report.offloaded_user_messages}")
    if report.summarized_messages:
        parts.append(f"summarized={report.summarized_messages}")
    if report.stage:
        parts.append(f"stage={report.stage}")
    if report.reason:
        parts.append(f"reason={report.reason}")
    if report.summary_token_usage is not None:
        parts.append(f"summary_usage=({format_token_usage(report.summary_token_usage)})")
    return " ".join(parts)


def format_session_status(status: SessionStatus) -> str:
    return (
        f"[session] id={status.session_id} origin={status.origin} "
        f"messages={status.message_count}\n"
        f"[context] {format_context_status(status.context)}"
    )


def format_memory_status(status: MemoryStatus) -> str:
    return "\n".join(
        (
            f"[memory] project={status.project_count} index={status.project_index_path}",
            f"[memory] user={status.user_count} index={status.user_index_path}",
            f"[memory] worker={status.worker_state} pending={status.pending_jobs}",
        )
    )


def format_permission_status(status: PermissionStatus) -> str:
    rows = [
        f"[permission] mode={status.effective_mode} source={status.mode_source}",
        "[permission] priority=session > local > project > user",
    ]
    for source in status.sources:
        path = str(source.path) if source.path is not None else "runtime"
        rows.append(
            f"[permission] {source.source} loaded={'yes' if source.loaded else 'no'} "
            f"rules={source.rule_count} path={path}"
        )
    return "\n".join(rows)


def format_token_status(status: TokenStatus) -> str:
    return (
        f"[usage] {format_token_usage(status.last_usage)}\n"
        f"[context] {format_context_status(status.context)}"
    )


def format_application_status(status: ApplicationStatus) -> str:
    return "\n".join(
        (
            f"[status] mode={status.mode} provider={status.provider} model={status.model}",
            f"[status] permission={status.permission.effective_mode}",
            f"[status] session={status.session.session_id} origin={status.session.origin} "
            f"messages={status.session.message_count}",
            format_token_status(status.token),
            f"[memory] project={status.memory.project_count} user={status.memory.user_count} "
            f"worker={status.memory.worker_state} pending={status.memory.pending_jobs}",
        )
    )
