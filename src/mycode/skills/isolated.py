from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from mycode.agent.cancellation import CancellationToken
from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.instructions import InstructionBundle
from mycode.permissions.service import PermissionService
from mycode.providers.base import LLMProvider
from mycode.providers.factory import create_provider
from mycode.prompts.modes import DynamicInstruction
from mycode.tool_safety import SYSTEM_TOOLS
from mycode.tools.registry import ToolRegistry
from mycode.types import AppConfig, Message, TokenUsage, ToolContext

from .models import (
    IsolatedSkillResult,
    SkillDefinition,
    SkillInvocation,
    SkillSnapshot,
)
from .runtime import SkillRuntime


ProviderFactory = Callable[[AppConfig], LLMProvider]
SnapshotSupplier = Callable[[], SkillSnapshot]


class IsolatedSkillRunner:
    def __init__(
        self,
        *,
        app_config: AppConfig,
        base_registry: ToolRegistry,
        tool_context: ToolContext,
        permission_service: PermissionService,
        snapshot_supplier: SnapshotSupplier,
        agent_config: AgentConfig = AgentConfig(),
        instruction_bundle: InstructionBundle | None = None,
        provider_factory: ProviderFactory = create_provider,
    ) -> None:
        self.app_config = app_config
        self.base_registry = base_registry
        self.tool_context = tool_context
        self.permission_service = permission_service
        self.snapshot_supplier = snapshot_supplier
        self.agent_config = agent_config
        self.instruction_bundle = instruction_bundle or InstructionBundle()
        self.provider_factory = provider_factory

    def run(
        self,
        invocation: SkillInvocation,
        definition: SkillDefinition,
        history: Sequence[Message],
        cancellation: CancellationToken,
        *,
        dynamic_instructions: Sequence[DynamicInstruction] = (),
        on_instructions_commit: Callable[[], None] | None = None,
        on_instructions_release: Callable[[], None] | None = None,
    ) -> IsolatedSkillResult:
        instructions_settled = False

        def commit_instructions() -> None:
            nonlocal instructions_settled
            if instructions_settled:
                return
            if on_instructions_commit is not None:
                on_instructions_commit()
            instructions_settled = True

        def release_instructions() -> None:
            nonlocal instructions_settled
            if instructions_settled:
                return
            if on_instructions_release is not None:
                on_instructions_release()
            instructions_settled = True

        if cancellation.is_cancelled():
            release_instructions()
            return IsolatedSkillResult("cancelled", "独立 Skill 已取消。")

        done_reason: str | None = None
        usage: TokenUsage | None = None
        child: AgentRunner | None = None
        try:
            snapshot = self.snapshot_supplier()
            runtime = SkillRuntime.for_isolated(snapshot, definition)
            provider_config = (
                replace(self.app_config, model=definition.model)
                if definition.model is not None
                else self.app_config
            )
            provider = self.provider_factory(provider_config)
            registry = self.base_registry.subset(
                name for name in self.base_registry.names() if name not in SYSTEM_TOOLS
            )
            child = AgentRunner(
                provider,
                registry,
                self.tool_context,
                config=self.agent_config,
                permission_service=self.permission_service,
                context_config=self.app_config.context,
                instruction_bundle=self.instruction_bundle,
                restored_messages=tuple(history),
                skill_runtime=runtime,
                isolated_skill_executor=self,
                initial_dynamic_instructions=tuple(dynamic_instructions),
                on_initial_instructions_commit=commit_instructions,
                on_initial_instructions_release=release_instructions,
            )
            for event in child.run(
                AgentRequest(
                    text=_isolated_user_message(definition, invocation.input_text),
                    mode=invocation.runtime_mode,
                ),
                cancellation,
            ):
                if event.type == "token_usage" and event.token_usage is not None:
                    usage = _merge_usage(usage, event.token_usage)
                elif event.type == "done":
                    done_reason = event.stop_reason

            final_text = _final_assistant_text(child.messages)
            if done_reason == "completed" and final_text:
                return IsolatedSkillResult("completed", final_text, usage)
            if done_reason == "cancelled" or cancellation.is_cancelled():
                return IsolatedSkillResult("cancelled", "独立 Skill 已取消。", usage)
            return IsolatedSkillResult(
                "failed",
                _failure_summary(definition.name, done_reason, bool(final_text)),
                usage,
            )
        except Exception as exc:
            return IsolatedSkillResult(
                "failed",
                f"独立 Skill `{definition.name}` 执行失败（{type(exc).__name__}）。",
                usage,
            )
        finally:
            if child is not None:
                try:
                    child.close()
                except Exception:
                    pass
            if not instructions_settled:
                try:
                    release_instructions()
                except Exception:
                    pass


def _isolated_user_message(definition: SkillDefinition, input_text: str) -> str:
    return f"使用 Skill `{definition.name}`。\n\nSkill 输入：\n{input_text}"


def _final_assistant_text(messages: Sequence[Message]) -> str:
    if not messages:
        return ""
    last = messages[-1]
    if last.role != "assistant" or last.tool_calls:
        return ""
    return last.content.strip()


def _failure_summary(name: str, reason: str | None, had_text: bool) -> str:
    labels = {
        "max_iterations": "达到迭代上限",
        "unknown_tools": "连续请求未知工具",
        "stream_error": "模型服务错误",
        "tool_parse_error": "工具调用解析失败",
        "context_overflow": "上下文超出预算",
        "session_error": "临时会话错误",
        "skill_failed": "Skill 执行失败",
    }
    if reason == "completed" and not had_text:
        detail = "没有产生最终文本"
    else:
        detail = labels.get(reason or "", "未正常完成")
    return f"独立 Skill `{name}` 执行失败：{detail}。"


def _merge_usage(current: TokenUsage | None, update: TokenUsage) -> TokenUsage:
    if current is None:
        return update

    def add(left: int | None, right: int | None) -> int | None:
        if left is None and right is None:
            return None
        return (left or 0) + (right or 0)

    return TokenUsage(
        input_tokens=add(current.input_tokens, update.input_tokens),
        output_tokens=add(current.output_tokens, update.output_tokens),
        total_tokens=add(current.total_tokens, update.total_tokens),
        cache_read_tokens=add(current.cache_read_tokens, update.cache_read_tokens),
        cache_creation_tokens=add(current.cache_creation_tokens, update.cache_creation_tokens),
        cache_unavailable=current.cache_unavailable or update.cache_unavailable,
    )
