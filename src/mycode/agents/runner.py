from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import date

from mycode.agent.collector import CollectedResponse, StreamCollector
from mycode.agent.executor import BatchToolExecutor
from mycode.agent.tools import ToolBatcher
from mycode.instructions import InstructionBundle
from mycode.prompts.builder import EnvironmentInfo, PromptBuilder
from mycode.prompts.modules import PromptOptions
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.types import (
    Message,
    ProviderError,
    TokenUsage,
    ToolContext,
    ToolExecutionResult,
)
from mycode.tools.file_cache import FileReadCache
from mycode.tools.registry import ToolRegistry

from .models import ChildRunSpec, PermissionAuditEntry, TaskOutcome
from .permissions import ChildPermissionFactory


ProviderSupplier = Callable[[str], LLMProvider]
BackgroundSupplier = Callable[[str], bool]


class ChildAgentExecutor:
    def __init__(
        self,
        *,
        provider_supplier: ProviderSupplier,
        base_registry: ToolRegistry,
        tool_context: ToolContext,
        permission_factory: ChildPermissionFactory,
        instruction_bundle: InstructionBundle | None = None,
        hook_runtime: object | None = None,
        background_supplier: BackgroundSupplier | None = None,
    ) -> None:
        self.provider_supplier = provider_supplier
        self.base_registry = base_registry
        self.tool_context = tool_context
        self.permission_factory = permission_factory
        self.instruction_bundle = instruction_bundle or InstructionBundle()
        self.hook_runtime = hook_runtime
        self.background_supplier = background_supplier or (
            lambda task_id: False
        )

    def run(self, spec: ChildRunSpec, cancellation: object) -> TaskOutcome:
        audit: list[PermissionAuditEntry] = []
        usage: TokenUsage | None = None
        hook_scope = None
        stop_reason = "internal_error"
        try:
            if cancellation.is_cancelled():
                stop_reason = "cancelled"
                return TaskOutcome("cancelled", failure_reason="任务已取消。")
            provider = self.provider_supplier(spec.model_id)
            permission = self.permission_factory.create(
                spec.role.permission_mode if spec.role is not None else "inherit",
                audit.append,
            )
            context = replace(
                self.tool_context,
                file_read_cache=FileReadCache(),
            )
            policy = spec.tool_policy
            if policy is None:
                raise ValueError("子 Agent 缺少工具策略。")
            if self.hook_runtime is not None:
                hook_scope = self.hook_runtime.fork_scope(
                    spec.session_id,
                    spec.task_id,
                    kind=spec.kind,
                    role=spec.role.name if spec.role else "",
                )
                hook_scope.begin_turn(spec.parent_mode, "agent")
                hook_scope.message_received(spec.prompt)

            template, messages, registry = self._initial_state(spec)
            max_iterations = spec.role.max_iterations if spec.role is not None else 8
            for _iteration in range(1, max_iterations + 1):
                if cancellation.is_cancelled():
                    stop_reason = "cancelled"
                    return TaskOutcome(
                        "cancelled",
                        failure_reason="任务已取消。",
                        token_usage=usage,
                        permission_audit=tuple(audit),
                    )
                request = replace(template, messages=tuple(messages))
                prompt_lease = None
                if hook_scope is not None and not (
                    spec.kind == "fork" and _iteration == 1
                ):
                    try:
                        prompt_lease = hook_scope.reserve_prompts()
                        request = replace(
                            request,
                            dynamic_system_messages=(
                                *request.dynamic_system_messages,
                                *prompt_lease.instructions,
                            ),
                        )
                    except Exception:
                        prompt_lease = None
                try:
                    collected = _collect(provider.stream_chat(request))
                    if prompt_lease is not None:
                        hook_scope.commit_prompt_lease(prompt_lease.lease_id)
                        prompt_lease = None
                finally:
                    if prompt_lease is not None:
                        try:
                            hook_scope.release_prompt_lease(prompt_lease.lease_id)
                        except Exception:
                            pass
                usage = merge_token_usage(usage, collected.token_usage)
                if collected.parse_errors:
                    stop_reason = "tool_parse_error"
                    return TaskOutcome(
                        "failed",
                        failure_reason=collected.parse_errors[0].message,
                        token_usage=usage,
                        permission_audit=tuple(audit),
                    )
                messages.append(
                    Message(
                        role="assistant",
                        content=collected.assistant_text,
                        tool_calls=collected.tool_calls,
                    )
                )
                if not collected.tool_calls:
                    result = collected.assistant_text.strip()
                    if hook_scope is not None:
                        hook_scope.message_sent(result)
                    stop_reason = "completed"
                    return TaskOutcome(
                        "completed",
                        result=result,
                        token_usage=usage,
                        permission_audit=tuple(audit),
                    )
                batches = ToolBatcher().batch(collected.tool_calls)
                executor = BatchToolExecutor(
                    registry,
                    context,
                    permission,
                    hook_scope,
                    tool_policy=policy,
                    background_supplier=lambda: self.background_supplier(spec.task_id),
                )
                results: list[tuple[str, ToolExecutionResult]] = []
                for item in executor.execute_batches(batches, cancellation):
                    if isinstance(item, tuple):
                        results.append(item)
                for tool_call_id, result in results:
                    messages.append(
                        Message(
                            role="tool",
                            tool_call_id=tool_call_id,
                            content=json.dumps(
                                asdict(result.complete),
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        )
                    )
            stop_reason = "max_iterations"
            return TaskOutcome(
                "failed",
                failure_reason="子 Agent 达到最大轮次。",
                token_usage=usage,
                permission_audit=tuple(audit),
            )
        except ProviderError as exc:
            stop_reason = "stream_error"
            return TaskOutcome(
                "failed",
                failure_reason=exc.user_message,
                token_usage=usage,
                permission_audit=tuple(audit),
            )
        except Exception as exc:
            stop_reason = "internal_error"
            return TaskOutcome(
                "failed",
                failure_reason=f"子 Agent 执行失败（{type(exc).__name__}）。",
                token_usage=usage,
                permission_audit=tuple(audit),
            )
        finally:
            if hook_scope is not None:
                try:
                    hook_scope.end_turn(stop_reason)
                    hook_scope.end_session(stop_reason)
                    hook_scope.close()
                except Exception:
                    pass

    def _initial_state(
        self, spec: ChildRunSpec
    ) -> tuple[ChatRequest, list[Message], ToolRegistry]:
        if spec.kind == "fork":
            if spec.fork_snapshot is None or spec.role is not None:
                raise ValueError("Fork 子 Agent 快照无效。")
            snapshot = spec.fork_snapshot
            messages = [*snapshot.request.messages, Message(role="user", content=spec.prompt)]
            return replace(snapshot.request, messages=()), messages, snapshot.registry.copy()

        if spec.role is None or spec.fork_snapshot is not None:
            raise ValueError("定义式子 Agent 角色无效。")
        policy = spec.tool_policy
        registry = policy.visible_registry(
            self.base_registry,
            background=spec.initial_background,
        )
        prompt = PromptBuilder().build(
            mode=spec.parent_mode,
            iteration=1,
            environment=EnvironmentInfo(
                cwd=str(self.tool_context.workspace_root),
                date=date.today().isoformat(),
                mode=spec.parent_mode,
            ),
            options=PromptOptions(custom_instructions=self.instruction_bundle.content),
        )
        optional = "\n\n".join(
            part for part in (prompt.optional_system_prompt, spec.role.system_prompt) if part
        )
        template = ChatRequest(
            stable_system_prompt=prompt.stable_system_prompt,
            dynamic_system_messages=(prompt.environment_message, *prompt.dynamic_system_messages),
            messages=(),
            optional_system_prompt=optional,
            tools=tuple(registry.tool_specs()),
        )
        return template, [Message(role="user", content=spec.prompt)], registry


def _collect(events: object) -> CollectedResponse:
    collected: CollectedResponse | None = None
    for item in StreamCollector().collect(events):
        if isinstance(item, CollectedResponse):
            collected = item
    return collected or CollectedResponse("", (), ())


def merge_token_usage(
    current: TokenUsage | None, update: TokenUsage | None
) -> TokenUsage | None:
    if update is None:
        return current
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
        cache_creation_tokens=add(
            current.cache_creation_tokens, update.cache_creation_tokens
        ),
        cache_unavailable=current.cache_unavailable or update.cache_unavailable,
    )
