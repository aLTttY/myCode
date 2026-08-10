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
from .memory import MemoryService, MemoryStore, MemoryWorker
from .mcp import MCPDiscoveryWarning, MCPManager, MCPManagerError, MCPTool
from .permissions.approval import TerminalApprovalHandler
from .permissions.config import PermissionConfigLoader
from .permissions.models import PermissionConfigSet
from .permissions.service import PermissionService
from .providers.factory import create_provider
from .sessions import SessionCatalog, SessionJournal
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
        # 加载配置，并根据配置创建对应的大模型 Provider
        config = load_config(Path(args.config))
        provider = create_provider(config)
        memory_provider = create_provider(config)
        tool_registry = create_default_registry()
        known_tools = {spec.name for spec in tool_registry.tool_specs()}
        workspace_root = Path.cwd()
        mcp_tool_prefixes = tuple(
            f"{server.name}__" for server in config.mcp_servers
        )
        permission_config = PermissionConfigLoader(
            known_tools,
            mcp_tool_prefixes=mcp_tool_prefixes,
        ).load(
            workspace_root,
            args.permission_mode,
        )
        permission_service = PermissionService(
            permission_config,
            TerminalApprovalHandler(),
            mcp_tool_prefixes=mcp_tool_prefixes,
        )
    except ConfigError as exc:
        print(f"配置错误：{exc.user_message}", file=sys.stderr)
        return 1

    mcp_manager = MCPManager(config.mcp_servers)
    journal = None
    memory_worker = None
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
        )
        try:
            return _run_interactive(
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
            )
        finally:
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
    finally:
        mcp_manager.close()


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
        session_id, warnings = switch()
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
) -> int:
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
                return 0
            except EOFError:
                print()
                return 0

            route = router.route(raw_text)
            if route.kind == "empty":
                continue
            if route.kind == "exit":
                print("已退出。")
                return 0
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


def _run_agent_turn(
    agent: AgentRunner,
    request: AgentRequest,
    on_token_usage,
) -> None:
    assistant_started = False
    cancellation = CancellationToken()
    try:
        for event in agent.run(request, cancellation):
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
