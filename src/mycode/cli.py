from __future__ import annotations

import argparse
from pathlib import Path
import sys
from collections.abc import Sequence

from prompt_toolkit import PromptSession, prompt
from prompt_toolkit.shortcuts import clear
from prompt_toolkit.shortcuts.prompt import CompleteStyle

from .agent.cancellation import CancellationToken
from .agent.config import AgentRequest
from .agent.runner import AgentRunner
from .commands import (
    ApplicationStatus,
    CommandDispatcher,
    CommandRegistrationError,
    InputRouter,
    MemoryStatus,
    PermissionSourceStatus,
    PermissionStatus,
    RuntimeMode,
    SessionStatus,
    SlashCommandCompleter,
    TokenStatus,
    create_default_command_registry,
    create_slash_command_key_bindings,
)
from .config import load_config
from .instructions import InstructionLoader
from .hooks.actions import HookActionExecutor
from .hooks.config import HookConfigLoader
from .hooks.events import HookEventFactory
from .hooks.models import HookDiagnostic, PromptAction
from .hooks.runtime import HookRuntime
from .memory import MemoryService, MemoryStore, MemoryWorker
from .mcp import MCPDiscoveryWarning, MCPManager, MCPManagerError, MCPTool
from .permissions.approval import TerminalApprovalHandler
from .permissions.config import PermissionConfigLoader
from .permissions.models import PermissionConfigSet
from .permissions.service import PermissionService
from .providers.factory import create_provider
from .sessions import SessionCatalog, SessionJournal
from .skills.catalog import SkillCatalog
from .skills.commands import commands_from_snapshot
from .skills.isolated import IsolatedSkillRunner
from .skills.models import SkillCatalogError
from .skills.runtime import SkillRuntime
from .tool_safety import SYSTEM_TOOLS
from .tools.registry import create_default_registry
from .context.models import CompactionReport
from .types import ConfigError, ProviderError, TokenUsage, ToolContext, ToolError


# 未指定 --config 时使用的默认配置文件
DEFAULT_CONFIG_PATH = "config.yaml"


_ACTIVE_PROMPT_SESSION: PromptSession[str] | None = None


def read_user_input(prompt_text: str) -> str:
    """读取终端输入。"""
    if _ACTIVE_PROMPT_SESSION is not None:
        return _ACTIVE_PROMPT_SESSION.prompt(prompt_text)
    return prompt(prompt_text)


def main(argv: Sequence[str] | None = None) -> int:
    # 解析命令行参数，例如：mycode --config custom.yaml
    parser = argparse.ArgumentParser(
        prog="mycode",
        description="Mycode 命令行 AI 编程助手",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="配置文件路径",
    )
    parser.add_argument(
        "--permission-mode",
        choices=("strict", "default", "allow"),
        default=None,
        help="覆盖本次进程的权限模式",
    )
    parser.add_argument(
        "--new",
        action="store_true",
        help="跳过自动恢复并创建新会话",
    )
    args = parser.parse_args(argv)

    try:
        command_registry = create_default_command_registry()
    except CommandRegistrationError as exc:
        print(f"命令注册错误：{exc}", file=sys.stderr)
        return 1

    try:
        # Hook 必须在 Provider、MCP 和后台服务初始化前完成整体校验。
        workspace_root = Path.cwd()
        config = load_config(Path(args.config))
        hook_snapshot = HookConfigLoader().load(workspace_root)
        provider = create_provider(config)
        memory_provider = create_provider(config)
        tool_registry = create_default_registry()
        mcp_tool_prefixes = tuple(
            f"{server.name}__" for server in config.mcp_servers
        )
    except ConfigError as exc:
        print(f"配置错误：{exc.user_message}", file=sys.stderr)
        return 1

    mcp_manager = MCPManager(config.mcp_servers)
    journal = None
    memory_worker = None
    hook_runtime: HookRuntime | None = None
    try:
        try:
            remote_tools, discovery_warnings = mcp_manager.discover()
        except MCPManagerError as exc:
            remote_tools = []
            discovery_warnings = [
                MCPDiscoveryWarning("mcp", "connect", exc.user_message)
            ]

        for remote_tool in remote_tools:
            try:
                tool_registry.register(MCPTool(remote_tool, mcp_manager))
            except ToolError as exc:
                discovery_warnings.append(
                    MCPDiscoveryWarning(
                        remote_tool.server_name,
                        "registration",
                        exc.user_message,
                    )
                )

        for warning in discovery_warnings:
            print(
                f"[mcp] {warning.server_name} {warning.stage} 失败：{warning.message}",
                file=sys.stderr,
            )

        reserved_commands = tuple(
            token
            for command in command_registry.commands(include_hidden=True)
            for token in (command.name, *command.aliases)
        )
        skill_catalog = SkillCatalog(workspace_root)
        skill_snapshot = skill_catalog.load_initial(
            set(tool_registry.names()) | set(SYSTEM_TOOLS),
            reserved_commands,
        )
        skill_runtime = SkillRuntime(skill_snapshot)
        command_registry.replace_dynamic(commands_from_snapshot(skill_snapshot))
        known_permission_tools = set(tool_registry.names()) | set(skill_snapshot.dedicated_tools) | set(SYSTEM_TOOLS)
        permission_config = PermissionConfigLoader(
            known_permission_tools,
            mcp_tool_prefixes=mcp_tool_prefixes,
        ).load(workspace_root, args.permission_mode)
        permission_service = PermissionService(
            permission_config,
            TerminalApprovalHandler(),
            mcp_tool_prefixes=mcp_tool_prefixes,
        )
        permission_service.update_dynamic_call_tools(set(skill_snapshot.dedicated_tools))
        _print_skill_diagnostics(skill_snapshot.diagnostics)

        catalog = SessionCatalog(workspace_root)
        cleanup = catalog.cleanup_expired()
        for warning in cleanup.warnings:
            print(f"[session] {warning.session_id} 清理失败：{warning.message}", file=sys.stderr)
        restored = None if args.new else catalog.latest()
        if restored is None or restored.summary is None:
            journal = SessionJournal(workspace_root)
            restored_messages = ()
            time_gap_reminder = ""
            session_origin = "new"
            print(f"[session] 新会话 {journal.session_id}")
        else:
            journal = SessionJournal(workspace_root, restored.summary.session_id)
            restored_messages = restored.messages
            time_gap_reminder = _time_gap_message(restored.gap) if restored.needs_time_gap_reminder else ""
            session_origin = "restored"
            print(
                f"[session] 已恢复 {journal.session_id} messages={len(restored.messages)} "
                f"bad_lines={restored.bad_line_count} truncated={restored.truncated_message_count}"
            )

        instruction_bundle = InstructionLoader().load(workspace_root)
        for warning in instruction_bundle.warnings:
            print(f"[instructions] {warning.code}: {warning.source} -> {warning.target}", file=sys.stderr)
        memory_store = MemoryStore(workspace_root)
        for scope in ("project", "user"):
            try:
                memory_store.reconcile(scope)
            except Exception as exc:
                print(f"[memory] {scope} 索引协调失败（{type(exc).__name__}）。", file=sys.stderr)
        memory_worker = MemoryWorker(MemoryService(memory_provider, memory_store))
        if hook_snapshot.rules:
            needs_executor = any(
                not isinstance(rule.action, PromptAction) for rule in hook_snapshot.rules
            )
            hook_actions = (
                HookActionExecutor(workspace_root) if needs_executor else None
            )
            hook_runtime = HookRuntime(
                hook_snapshot,
                HookEventFactory(workspace_root),
                hook_actions,
                _print_hook_diagnostic,
            )
        isolated_skill_runner = IsolatedSkillRunner(
            app_config=config,
            base_registry=tool_registry,
            tool_context=ToolContext(workspace_root=workspace_root),
            permission_service=permission_service,
            snapshot_supplier=lambda: skill_runtime.snapshot,
            instruction_bundle=instruction_bundle,
        )

        # 创建 Agent 执行器：
        # provider 负责调用模型，registry 保存工具，workspace_root 限制工具工作目录
        agent = AgentRunner(
            provider,
            full_registry=tool_registry,
            tool_context=ToolContext(workspace_root=workspace_root),
            permission_service=permission_service,
            context_config=config.context,
            session_journal=journal,
            instruction_bundle=instruction_bundle,
            memory_store=memory_store,
            memory_worker=memory_worker,
            restored_messages=restored_messages,
            time_gap_reminder=time_gap_reminder,
            skill_runtime=skill_runtime,
            isolated_skill_executor=isolated_skill_runner,
            hook_runtime=hook_runtime,
        )
        exit_reason = "fatal_error"
        if hook_runtime is not None:
            hook_runtime.begin_session(journal.session_id, session_origin)
        try:
            exit_reason = _run_interactive(
                agent,
                command_registry=command_registry,
                config=config,
                permission_config=permission_config,
                permission_service=permission_service,
                memory_store=memory_store,
                memory_worker=memory_worker,
                workspace_root=workspace_root,
                session_origin=session_origin,
                permission_mode_override=args.permission_mode,
                skill_catalog=skill_catalog,
                skill_runtime=skill_runtime,
                reserved_commands=reserved_commands,
            )
            return 0
        finally:
            if hook_runtime is not None:
                hook_runtime.end_session(exit_reason)
            close = getattr(agent, "close", None)
            warning = close() if close is not None else None
            if warning:
                print(f"[context] {warning}", file=sys.stderr)
            if journal is not None:
                journal.close()
            if memory_worker is not None:
                for notice in memory_worker.drain(0):
                    if notice.code != "updated":
                        print(f"[memory] {notice.message}", file=sys.stderr)
            if hook_runtime is not None:
                hook_runtime.close()
    except (ConfigError, SkillCatalogError, CommandRegistrationError, ToolError) as exc:
        message = getattr(exc, "user_message", str(exc))
        print(f"Skill 启动错误：{message}", file=sys.stderr)
        return 1
    finally:
        if hook_runtime is not None:
            hook_runtime.close()
        mcp_manager.close()


def _print_hook_diagnostic(diagnostic: HookDiagnostic) -> None:
    print(
        f"[hook] {diagnostic.source_path}:{diagnostic.source_index} "
        f"{diagnostic.event} {diagnostic.code}: {diagnostic.message}",
        file=sys.stderr,
    )


class TerminalCommandUI:
    def __init__(
        self,
        agent: AgentRunner,
        config,
        permission_config: PermissionConfigSet,
        permission_service: PermissionService,
        memory_store: MemoryStore,
        memory_worker: MemoryWorker,
        workspace_root: Path,
        session_origin: str,
        permission_mode_override: str | None = None,
    ) -> None:
        self.agent = agent
        self.config = config
        self.permission_config = permission_config
        self.permission_service = permission_service
        self.memory_store = memory_store
        self.memory_worker = memory_worker
        self.workspace_root = workspace_root
        self._current_mode: RuntimeMode = "default"
        self._session_origin = session_origin
        self._last_token_usage: TokenUsage | None = None
        self._permission_mode_override = permission_mode_override
        self._prompt_session: PromptSession[str] | None = None

    @property
    def current_mode(self) -> RuntimeMode:
        return self._current_mode

    @property
    def session_origin(self) -> str:
        return self._session_origin

    @property
    def last_token_usage(self) -> TokenUsage | None:
        return self._last_token_usage

    def attach_prompt_session(self, session: PromptSession[str]) -> None:
        self._prompt_session = session

    def bottom_toolbar(self) -> str:
        return "[PLAN]" if self._current_mode == "plan" else "[DEFAULT]"

    def display_message(self, text: str, *, error: bool = False) -> None:
        print(text, file=sys.stderr if error else sys.stdout, flush=True)

    def clear_screen(self) -> None:
        clear()

    def send_user_message(
        self,
        text: str,
        *,
        mode_override: RuntimeMode | None = None,
    ) -> None:
        request = AgentRequest(text=text, mode=mode_override or self._current_mode)
        _run_agent_turn(self.agent, request, self._remember_token_usage)

    def invoke_skill(self, name: str, input_text: str) -> None:
        cancellation = CancellationToken()
        events = self.agent.invoke_skill(
            name,
            input_text,
            mode=self._current_mode,
            cancellation=cancellation,
        )
        _render_agent_events(self.agent, events, cancellation, self._remember_token_usage)

    def switch_mode(self, mode: RuntimeMode) -> None:
        self._current_mode = mode

    def compact_context(self) -> CompactionReport:
        report = self.agent.compact(self._current_mode)
        if report.summary_token_usage is not None:
            self._last_token_usage = report.summary_token_usage
        return report

    def token_status(self) -> TokenStatus:
        return TokenStatus(
            last_usage=self._last_token_usage,
            context=self.agent.context_status(self._current_mode),
        )

    def session_status(self) -> SessionStatus:
        context = self.agent.context_status(self._current_mode)
        journal = getattr(self.agent, "session_journal", None)
        session_id = getattr(journal, "session_id", "unavailable")
        return SessionStatus(
            session_id=session_id,
            message_count=context.message_count,
            origin=self._session_origin,
            context=context,
        )

    def memory_status(self) -> MemoryStatus:
        worker = self.memory_worker.status()
        return MemoryStatus(
            project_count=len(self.memory_store.list_notes("project")),
            user_count=len(self.memory_store.list_notes("user")),
            project_index_path=self.memory_store.root_for("project") / "index.md",
            user_index_path=self.memory_store.root_for("user") / "index.md",
            worker_state=worker.state,
            pending_jobs=worker.pending_jobs,
        )

    def permission_status(self) -> PermissionStatus:
        config = self.permission_config
        user_path = Path.home() / ".mycode" / "permissions.yaml"
        project_path = self.workspace_root / ".mycode" / "permissions.yaml"
        local_path = self.workspace_root / ".mycode" / "permissions.local.yaml"
        session_count = self.permission_service.session_rule_count
        return PermissionStatus(
            effective_mode=config.effective_mode,
            mode_source=self._permission_mode_source(),
            sources=(
                PermissionSourceStatus(
                    "session", None, session_count > 0, session_count
                ),
                PermissionSourceStatus(
                    "local", local_path, local_path.is_file(), len(config.local.rules)
                ),
                PermissionSourceStatus(
                    "project", project_path, project_path.is_file(), len(config.project.rules)
                ),
                PermissionSourceStatus(
                    "user", user_path, user_path.is_file(), len(config.user.rules)
                ),
            ),
        )

    def application_status(self) -> ApplicationStatus:
        token = self.token_status()
        return ApplicationStatus(
            mode=self._current_mode,
            provider=self.config.protocol,
            model=self.config.model,
            token=token,
            session=SessionStatus(
                session_id=getattr(
                    getattr(self.agent, "session_journal", None),
                    "session_id",
                    "unavailable",
                ),
                message_count=token.context.message_count,
                origin=self._session_origin,
                context=token.context,
            ),
            memory=self.memory_status(),
            permission=self.permission_status(),
        )

    def new_session(self) -> None:
        switch = getattr(self.agent, "new_session", None)
        if switch is None:
            self.display_message(
                "[session] 当前 Agent 不支持新建会话。", error=True
            )
            return
        hook_runtime = getattr(self.agent, "hook_runtime", None)
        if hook_runtime is not None:
            try:
                hook_runtime.end_session("switched")
            except Exception:
                pass
        session_id, warnings = switch()
        if hook_runtime is not None:
            try:
                hook_runtime.begin_session(session_id, "new")
            except Exception:
                pass
        self._session_origin = "new"
        self._last_token_usage = None
        self.display_message(f"[session] 新会话 {session_id}")
        for warning in warnings:
            self.display_message(f"[session] {warning}", error=True)

    def refresh_status(self) -> None:
        session = self._prompt_session
        if session is not None and session.app.is_running:
            session.app.invalidate()

    def _remember_token_usage(self, usage: TokenUsage | None) -> None:
        if usage is not None:
            self._last_token_usage = usage

    def _permission_mode_source(self) -> str:
        if self._permission_mode_override is not None:
            return "cli"
        if self.permission_config.local.mode is not None:
            return "local"
        if self.permission_config.project.mode is not None:
            return "project"
        if self.permission_config.user.mode is not None:
            return "user"
        return "default"


def _run_interactive(
    agent: AgentRunner,
    *,
    command_registry,
    config,
    permission_config: PermissionConfigSet,
    permission_service: PermissionService,
    memory_store: MemoryStore,
    memory_worker: MemoryWorker,
    workspace_root: Path,
    session_origin: str,
    permission_mode_override: str | None,
    skill_catalog: SkillCatalog | None = None,
    skill_runtime: SkillRuntime | None = None,
    reserved_commands: tuple[str, ...] = (),
) -> str:
    global _ACTIVE_PROMPT_SESSION

    ui = TerminalCommandUI(
        agent,
        config,
        permission_config,
        permission_service,
        memory_store,
        memory_worker,
        workspace_root,
        session_origin,
        permission_mode_override,
    )
    prompt_session: PromptSession[str] = PromptSession(
        completer=SlashCommandCompleter(command_registry),
        key_bindings=create_slash_command_key_bindings(),
        complete_while_typing=False,
        complete_style=CompleteStyle.COLUMN,
        bottom_toolbar=ui.bottom_toolbar,
    )
    ui.attach_prompt_session(prompt_session)
    router = InputRouter(command_registry)
    dispatcher = CommandDispatcher(command_registry)

    print(
        "Mycode 已启动。输入 /help 查看命令；exit、quit 或 退出 结束。"
    )
    previous_session = _ACTIVE_PROMPT_SESSION
    _ACTIVE_PROMPT_SESSION = prompt_session
    try:
        while True:
            _print_memory_notices(agent)
            try:
                raw_text = read_user_input("> ")
            except KeyboardInterrupt:
                print("\n已退出。")
                return "interrupt"
            except EOFError:
                print()
                return "eof"

            if skill_catalog is not None and skill_runtime is not None:
                active_registry = getattr(agent, "full_registry", None)
                if active_registry is not None:
                    _refresh_skills(
                        skill_catalog,
                        skill_runtime,
                        active_registry,
                        command_registry,
                        permission_service,
                        reserved_commands,
                    )

            route = router.route(raw_text)
            if route.kind == "empty":
                continue
            if route.kind == "exit":
                print("已退出。")
                return "exit"
            if route.kind == "error":
                ui.display_message(route.message, error=True)
                continue
            if route.kind == "plain":
                ui.send_user_message(route.text)
                continue
            if route.invocation is not None:
                dispatcher.dispatch(route.invocation, ui)
    finally:
        _ACTIVE_PROMPT_SESSION = previous_session


def _refresh_skills(
    catalog: SkillCatalog,
    runtime: SkillRuntime,
    tool_registry,
    command_registry,
    permission_service: PermissionService,
    reserved_commands: tuple[str, ...],
) -> None:
    report = catalog.refresh(
        runtime.snapshot,
        set(tool_registry.names()) | set(SYSTEM_TOOLS),
        reserved_commands,
    )
    if not report.changed:
        return
    try:
        command_registry.replace_dynamic(commands_from_snapshot(report.snapshot))
    except CommandRegistrationError as exc:
        print(f"[skills] 热更新失败：{exc}", file=sys.stderr)
        return
    permission_service.update_dynamic_call_tools(set(report.snapshot.dedicated_tools))
    update = runtime.publish(report.snapshot)
    _print_skill_diagnostics(report.diagnostics)
    changes: list[str] = []
    if update.replaced:
        changes.append(f"已替换激活项={','.join(update.replaced)}")
    if update.deactivated:
        changes.append(f"已停用={','.join(update.deactivated)}")
    suffix = f"（{'；'.join(changes)}）" if changes else ""
    print(f"[skills] 已热更新{suffix}", file=sys.stderr)


def _print_skill_diagnostics(diagnostics) -> None:
    for diagnostic in diagnostics:
        print(
            f"[skills] {diagnostic.level} {diagnostic.code}: "
            f"{diagnostic.source_id} -> {diagnostic.message}",
            file=sys.stderr,
        )


def _run_agent_turn(
    agent: AgentRunner,
    request: AgentRequest,
    on_token_usage,
) -> None:
    cancellation = CancellationToken()
    _render_agent_events(agent, agent.run(request, cancellation), cancellation, on_token_usage)


def _render_agent_events(agent, events, cancellation, on_token_usage) -> None:
    assistant_started = False
    try:
        for event in events:
            if event.type == "text_delta":
                if not assistant_started:
                    print("● ", end="", flush=True)
                    assistant_started = True
                print(event.text, end="", flush=True)

            elif event.type == "progress":
                print(
                    f"\n[agent] iteration {event.iteration}/{event.max_iterations}",
                    flush=True,
                )

            elif event.type == "tool_call_started":
                args_text = format_tool_arguments(event.tool_arguments)
                suffix = f"：{args_text}" if args_text else ""
                print(f"\n[tool] {event.tool_name} 开始{suffix}", flush=True)

            elif event.type == "tool_result":
                result = event.tool_result
                status = "成功" if result and result.ok else "失败"
                message = result.message if result else ""
                print(f"[tool] {event.tool_name} {status}：{message}", flush=True)

            elif event.type == "token_usage":
                on_token_usage(event.token_usage)
                usage_text = format_token_usage(event.token_usage)
                if usage_text:
                    print(f"\n[usage] {usage_text}", flush=True)

            elif event.type == "context_status":
                if event.context_report is not None:
                    print(
                        f"\n[context] {format_compaction_report(event.context_report)}",
                        flush=True,
                    )

            elif event.type == "done":
                if event.stop_reason and event.stop_reason != "completed":
                    print(f"\n[agent] 停止：{event.message}", flush=True)

            elif event.type == "error":
                print(
                    f"\n[agent] 错误：{event.message}",
                    file=sys.stderr,
                    flush=True,
                )

        print()
        _print_memory_notices(agent)
    except KeyboardInterrupt:
        cancellation.cancel()
        close = getattr(events, "close", None)
        if close is not None:
            try:
                close()
            except Exception:
                pass
        print("\n已取消。")
    except ProviderError as exc:
        print(f"请求错误：{exc.user_message}", file=sys.stderr)


def _print_memory_notices(agent: AgentRunner) -> None:
    take = getattr(agent, "take_memory_notices", None)
    if take is None:
        return
    for notice in take():
        if notice.code != "updated":
            print(f"[memory] {notice.message}", file=sys.stderr)


def _time_gap_message(gap) -> str:
    if gap is None:
        return ""
    hours = max(0, int(gap.total_seconds() // 3600))
    amount = f"{hours // 24} 天" if hours >= 48 else f"{hours} 小时"
    return f"距上次会话活动约 {amount}。文件、依赖、服务和需求状态可能已变化，请先核实再继续。"

def format_token_usage(usage: TokenUsage | None) -> str:
    """将 TokenUsage 转换为终端可读文本。"""

    if usage is None:
        return ""

    parts: list[str] = []

    # 使用 is not None，避免数值为 0 时被误判为没有数据
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

    # Provider 不支持缓存统计时，明确显示 unavailable
    if (
            usage.cache_unavailable
            and usage.cache_read_tokens is None
            and usage.cache_creation_tokens is None
    ):
        parts.append("cache=unavailable")

    return " ".join(parts)


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
    return " ".join(parts)


def format_tool_arguments(
        arguments: dict[str, object] | None,
) -> str:
    """筛选并缩短工具参数，供终端日志展示。"""

    if not arguments:
        return ""

    shown: list[str] = []

    for key, value in arguments.items():
        # 这些字段通常很长或可能包含敏感内容，不直接打印
        if key in {"content", "old_text", "new_text", "command"}:
            continue

        if isinstance(value, str):
            text = value
        elif isinstance(value, (int, float, bool)):
            text = str(value)
        else:
            # list、dict 等复杂结构暂不展示
            continue

        # 单个参数最多显示 120 个字符
        if len(text) > 120:
            text = text[:117] + "..."

        shown.append(f"{key}={text}")

    return " ".join(shown)
