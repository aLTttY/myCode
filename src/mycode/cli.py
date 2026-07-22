from __future__ import annotations

import argparse
from pathlib import Path
import sys
from collections.abc import Sequence

from prompt_toolkit import prompt

from .agent.cancellation import CancellationToken
from .agent.config import AgentRequest
from .agent.runner import AgentRunner
from .config import load_config
from .instructions import InstructionLoader
from .memory import MemoryService, MemoryStore, MemoryWorker
from .mcp import MCPDiscoveryWarning, MCPManager, MCPManagerError, MCPTool
from .permissions.approval import TerminalApprovalHandler
from .permissions.config import PermissionConfigLoader
from .permissions.service import PermissionService
from .providers.factory import create_provider
from .sessions import SessionCatalog, SessionJournal
from .tools.registry import create_default_registry
from .context.models import CompactionReport
from .types import ConfigError, ProviderError, TokenUsage, ToolContext, ToolError


# 支持的退出命令
EXIT_COMMANDS = {"exit", "quit", "退出"}

# 未指定 --config 时使用的默认配置文件
DEFAULT_CONFIG_PATH = "config.yaml"


def read_user_input(prompt_text: str) -> str:
    """读取终端输入。"""
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
        # 加载配置，并根据配置创建对应的大模型 Provider
        config = load_config(Path(args.config))
        provider = create_provider(config)
        memory_provider = create_provider(config)
        registry = create_default_registry()
        known_tools = {spec.name for spec in registry.tool_specs()}
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
                registry.register(MCPTool(remote_tool, mcp_manager))
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
            print(f"[session] 新会话 {journal.session_id}")
        else:
            journal = SessionJournal(workspace_root, restored.summary.session_id)
            restored_messages = restored.messages
            time_gap_reminder = _time_gap_message(restored.gap) if restored.needs_time_gap_reminder else ""
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
            full_registry=registry,
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
            return _run_interactive(agent)
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


def _run_interactive(agent: AgentRunner) -> int:
    print("Mycode 已启动。输入 /plan 生成计划，/do 执行计划，/compact 压缩上下文，/new 新建会话，exit、quit 或 退出 结束。")

    while True:
        _print_memory_notices(agent)
        try:
            user_text = read_user_input("> ").strip()
        except KeyboardInterrupt:
            # 等待输入时按 Ctrl+C，直接退出程序
            print("\n已退出。")
            return 0
        except EOFError:
            # Ctrl+D 或输入流结束
            print()
            return 0

        if not user_text:
            continue

        if user_text.lower() in EXIT_COMMANDS:
            print("已退出。")
            return 0

        if user_text == "/compact":
            report = agent.compact()
            print(f"[context] {format_compaction_report(report)}", flush=True)
            continue

        if user_text == "/new":
            switch = getattr(agent, "new_session", None)
            if switch is None:
                print("[session] 当前 Agent 不支持新建会话。", file=sys.stderr)
                continue
            session_id, warnings = switch()
            print(f"[session] 新会话 {session_id}", flush=True)
            for warning in warnings:
                print(f"[session] {warning}", file=sys.stderr)
            continue

        try:
            # 控制“● ”只在第一段模型文本到来时打印一次
            assistant_started = False

            # 当前请求的取消令牌，执行中按 Ctrl+C 时使用
            cancellation = CancellationToken()

            # 将普通输入、/plan、/do 转换成统一的 AgentRequest
            request = parse_agent_request(user_text)

            # AgentRunner 通过事件流持续返回执行进度、文本和工具结果
            for event in agent.run(request, cancellation):
                if event.type == "text_delta":
                    if not assistant_started:
                        print("● ", end="", flush=True)
                        assistant_started = True

                    # 模型文本是分段返回的，因此不换行并立即刷新
                    print(event.text, end="", flush=True)

                elif event.type == "progress":
                    print(
                        f"\n[agent] iteration "
                        f"{event.iteration}/{event.max_iterations}",
                        flush=True,
                    )

                elif event.type == "tool_call_started":
                    # 只展示适合打印的工具参数，避免输出大段文件内容
                    args_text = format_tool_arguments(event.tool_arguments)
                    suffix = f"：{args_text}" if args_text else ""

                    print(
                        f"\n[tool] {event.tool_name} 开始{suffix}",
                        flush=True,
                    )

                elif event.type == "tool_result":
                    result = event.tool_result

                    # result 不为空且 ok=True 时才算成功
                    status = "成功" if result and result.ok else "失败"
                    message = result.message if result else ""

                    print(
                        f"[tool] {event.tool_name} {status}：{message}",
                        flush=True,
                    )

                elif event.type == "token_usage":
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
                    # 正常完成时不额外提示，异常停止时显示原因
                    if event.stop_reason and event.stop_reason != "completed":
                        print(
                            f"\n[agent] 停止：{event.message}",
                            flush=True,
                        )

                elif event.type == "error":
                    print(
                        f"\n[agent] 错误：{event.message}",
                        file=sys.stderr,
                        flush=True,
                    )

            # 本轮回答结束后换行，避免下一次输入提示符粘在后面
            print()
            _print_memory_notices(agent)

        except KeyboardInterrupt:
            # Agent 执行过程中按 Ctrl+C，只取消本轮任务，不退出 CLI
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

def parse_agent_request(user_text: str) -> AgentRequest:
    """根据命令前缀决定 Agent 的运行模式。"""

    if user_text.startswith("/plan"):
        return AgentRequest(
            text=user_text.removeprefix("/plan").strip(),
            mode="plan",
        )

    if user_text.startswith("/do"):
        return AgentRequest(
            text=user_text.removeprefix("/do").strip(),
            mode="do",
        )

    return AgentRequest(text=user_text, mode="default")


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
