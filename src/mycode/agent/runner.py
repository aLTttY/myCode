from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date

from mycode.agent.cancellation import CancellationToken
from mycode.agent.collector import CollectedResponse, StreamCollector
from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.events import AgentEvent, done_event, progress_event
from mycode.agent.executor import BatchToolExecutor
from mycode.agent.tools import ToolBatcher, create_readonly_registry
from mycode.permissions.service import PermissionService
from mycode.prompts.builder import EnvironmentInfo, PromptBuilder
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.tools.descriptions import reinforce_tool_specs
from mycode.types import Message, ProviderError, ToolCall, ToolContext, ToolResult
from mycode.tools.registry import ToolRegistry


class AgentRunner:
    def __init__(
        self,
        provider: LLMProvider,
        full_registry: ToolRegistry,
        tool_context: ToolContext,
        config: AgentConfig = AgentConfig(),
        permission_service: PermissionService | None = None,
    ) -> None:
        self.provider = provider
        self.full_registry = full_registry
        self.tool_context = tool_context
        self.config = config
        self.permission_service = permission_service or PermissionService.with_mode("default")
        self.messages: list[Message] = []

    def run(
        self,
        request: AgentRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[AgentEvent]:
        cancellation = cancellation or CancellationToken()
        registry = self._registry_for_request(request)
        self.messages.append(Message(role="user", content=request.text))
        consecutive_unknown_tools = 0

        for iteration in range(1, self.config.max_iterations + 1):
            if cancellation.is_cancelled():
                yield done_event("cancelled", "用户已取消。", iteration, self.config.max_iterations)
                return

            yield progress_event(iteration, self.config.max_iterations, f"iteration {iteration}/{self.config.max_iterations}")
            try:
                chat_request = self._chat_request(request, registry, iteration)
                provider_events = self.provider.stream_chat(chat_request)
                collected = yield from self._collect_provider_response(provider_events)
            except ProviderError as exc:
                yield AgentEvent(type="error", stop_reason="stream_error", message=exc.user_message)
                yield done_event("stream_error", exc.user_message, iteration, self.config.max_iterations)
                return

            if collected.parse_errors:
                message = collected.parse_errors[0].message
                yield AgentEvent(type="error", stop_reason="tool_parse_error", message=message)
                yield done_event("tool_parse_error", message, iteration, self.config.max_iterations)
                return

            if not collected.tool_calls:
                self.messages.append(Message(role="assistant", content=collected.assistant_text))
                yield done_event("completed", "任务完成。", iteration, self.config.max_iterations)
                return

            self.messages.append(
                Message(
                    role="assistant",
                    content=collected.assistant_text,
                    tool_calls=collected.tool_calls,
                )
            )

            batches = ToolBatcher().batch(collected.tool_calls)
            tool_results: list[tuple[str, ToolResult]] = []
            batch_executor = BatchToolExecutor(registry, self.tool_context, self.permission_service)
            for item in batch_executor.execute_batches(batches, cancellation):
                if isinstance(item, AgentEvent):
                    yield item
                else:
                    tool_call_id, result = item
                    tool_results.append((tool_call_id, result))
                    if _is_unknown_tool_result(result):
                        consecutive_unknown_tools += 1
                    else:
                        consecutive_unknown_tools = 0

            for tool_call_id, result in tool_results:
                self.messages.append(
                    Message(
                        role="tool",
                        content=json.dumps(asdict(result), ensure_ascii=False),
                        tool_call_id=tool_call_id,
                    )
                )

            if cancellation.is_cancelled():
                yield done_event("cancelled", "用户已取消。", iteration, self.config.max_iterations)
                return

            if consecutive_unknown_tools >= self.config.max_unknown_tool_calls:
                yield done_event(
                    "unknown_tools",
                    "连续请求未知工具，Agent 已停止。",
                    iteration,
                    self.config.max_iterations,
                )
                return

            if iteration == self.config.max_iterations:
                yield done_event(
                    "max_iterations",
                    "达到迭代上限，Agent 已停止。",
                    iteration,
                    self.config.max_iterations,
                )
                return

    def _collect_provider_response(self, events: Iterator) -> Iterator[AgentEvent | CollectedResponse]:
        collected: CollectedResponse | None = None
        for item in StreamCollector().collect(events):
            if isinstance(item, CollectedResponse):
                collected = item
            else:
                yield item
        if collected is None:
            collected = CollectedResponse(assistant_text="", tool_calls=(), parse_errors=())
        return collected

    def _registry_for_request(self, request: AgentRequest) -> ToolRegistry:
        if request.mode == "plan":
            return create_readonly_registry(self.full_registry)
        return self.full_registry

    def _chat_request(self, request: AgentRequest, registry: ToolRegistry, iteration: int) -> ChatRequest:
        environment = EnvironmentInfo(
            cwd=str(self.tool_context.workspace_root),
            date=date.today().isoformat(),
            mode=request.mode,
        )
        prompt = PromptBuilder(repeat_interval=self.config.prompt_repeat_interval).build(
            mode=request.mode,
            iteration=iteration,
            environment=environment,
        )
        return ChatRequest(
            stable_system_prompt=prompt.stable_system_prompt,
            dynamic_system_messages=(prompt.environment_message, *prompt.dynamic_system_messages),
            messages=tuple(self.messages),
            optional_system_prompt=prompt.optional_system_prompt,
            tools=reinforce_tool_specs(registry.tool_specs()),
        )


def _is_unknown_tool_result(result: ToolResult) -> bool:
    return not result.ok and "未知工具" in result.message
