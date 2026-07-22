from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import asdict
from datetime import date

from mycode.agent.cancellation import CancellationToken
from mycode.agent.collector import CollectedResponse, StreamCollector
from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.events import AgentEvent, done_event, progress_event
from mycode.agent.executor import BatchToolExecutor
from mycode.agent.tools import ToolBatcher, create_readonly_registry
from mycode.context.manager import ContextManager
from mycode.context.models import CompactionReport
from mycode.instructions import InstructionBundle
from mycode.memory import MemoryStore, MemoryWorker, TurnSnapshot
from mycode.permissions.service import PermissionService
from mycode.prompts.builder import EnvironmentInfo, PromptBuilder
from mycode.prompts.modes import DynamicInstruction
from mycode.prompts.modules import PromptOptions
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.sessions import SessionError, SessionJournal
from mycode.tools.descriptions import reinforce_tool_specs
from mycode.types import ContextConfig, Message, ProviderError, ToolCall, ToolContext, ToolExecutionResult, ToolResult
from mycode.tools.registry import ToolRegistry


class AgentRunner:
    def __init__(
        self,
        provider: LLMProvider,
        full_registry: ToolRegistry,
        tool_context: ToolContext,
        config: AgentConfig = AgentConfig(),
        permission_service: PermissionService | None = None,
        context_config: ContextConfig | None = None,
        session_journal: SessionJournal | None = None,
        instruction_bundle: InstructionBundle | None = None,
        memory_store: MemoryStore | None = None,
        memory_worker: MemoryWorker | None = None,
        restored_messages: Sequence[Message] = (),
        time_gap_reminder: str = "",
    ) -> None:
        self.provider = provider
        self.full_registry = full_registry
        self.tool_context = tool_context
        self.config = config
        self.permission_service = permission_service or PermissionService.with_mode("default")
        self.context_config = context_config or ContextConfig(window_tokens=128_000)
        self.context_manager = ContextManager(
            self.context_config,
            provider,
            tool_context.workspace_root,
        )
        if restored_messages:
            self.context_manager.import_messages(restored_messages)
        self.session_journal = session_journal
        self.instruction_bundle = instruction_bundle or InstructionBundle()
        self.memory_store = memory_store
        self.memory_worker = memory_worker
        self._time_gap_reminder = time_gap_reminder
        self._last_request: AgentRequest | None = None

    @property
    def messages(self):
        return self.context_manager.messages

    def run(
        self,
        request: AgentRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[AgentEvent]:
        cancellation = cancellation or CancellationToken()
        registry = self._registry_for_request(request)
        self._last_request = request
        try:
            self._append_message(Message(role="user", content=request.text))
        except SessionError as exc:
            yield AgentEvent(type="error", stop_reason="session_error", message=str(exc))
            yield done_event("session_error", str(exc))
            return
        consecutive_unknown_tools = 0
        assistant_parts: list[str] = []
        tool_summaries: list[str] = []

        for iteration in range(1, self.config.max_iterations + 1):
            if cancellation.is_cancelled():
                yield done_event("cancelled", "用户已取消。", iteration, self.config.max_iterations)
                return

            yield progress_event(iteration, self.config.max_iterations, f"iteration {iteration}/{self.config.max_iterations}")
            try:
                template = self._chat_request_template(request, registry, iteration)
                prepared = self.context_manager.prepare_request(template)
                if prepared.report.status != "not_needed":
                    yield AgentEvent(type="context_status", context_report=prepared.report)
                if not prepared.allowed:
                    message = (
                        f"上下文估算 {prepared.report.after_tokens} token，"
                        f"预算 {prepared.report.budget_tokens} token；{prepared.report.reason} "
                        "请执行 /compact 重试，或使用 /new 开始新会话。"
                    )
                    yield AgentEvent(type="error", stop_reason="context_overflow", message=message)
                    yield done_event("context_overflow", message, iteration, self.config.max_iterations)
                    return
                chat_request = prepared.request
                self._time_gap_reminder = ""
                provider_events = self.provider.stream_chat(chat_request)
                collected = yield from self._collect_provider_response(provider_events)
            except ProviderError as exc:
                yield AgentEvent(type="error", stop_reason="stream_error", message=exc.user_message)
                yield done_event("stream_error", exc.user_message, iteration, self.config.max_iterations)
                return

            self.context_manager.record_usage(chat_request, collected.token_usage)

            if collected.parse_errors:
                message = collected.parse_errors[0].message
                yield AgentEvent(type="error", stop_reason="tool_parse_error", message=message)
                yield done_event("tool_parse_error", message, iteration, self.config.max_iterations)
                return

            assistant_parts.append(collected.assistant_text)

            if not collected.tool_calls:
                try:
                    self._append_message(Message(role="assistant", content=collected.assistant_text))
                except SessionError as exc:
                    yield AgentEvent(type="error", stop_reason="session_error", message=str(exc))
                    yield done_event("session_error", str(exc), iteration, self.config.max_iterations)
                    return
                yield done_event("completed", "任务完成。", iteration, self.config.max_iterations)
                self._submit_memory(request.text, "\n".join(part for part in assistant_parts if part), tool_summaries)
                return

            try:
                self._append_message(
                    Message(role="assistant", content=collected.assistant_text, tool_calls=collected.tool_calls)
                )
            except SessionError as exc:
                yield AgentEvent(type="error", stop_reason="session_error", message=str(exc))
                yield done_event("session_error", str(exc), iteration, self.config.max_iterations)
                return

            batches = ToolBatcher().batch(collected.tool_calls)
            tool_results: list[tuple[str, ToolExecutionResult]] = []
            batch_executor = BatchToolExecutor(registry, self.tool_context, self.permission_service)
            for item in batch_executor.execute_batches(batches, cancellation):
                if isinstance(item, AgentEvent):
                    yield item
                else:
                    tool_call_id, result = item
                    tool_results.append((tool_call_id, result))
                    tool_summaries.append(
                        f"{tool_call_id}: {'ok' if result.display.ok else 'failed'}: {result.display.message[:200]}"
                    )
                    if _is_unknown_tool_result(result):
                        consecutive_unknown_tools += 1
                    else:
                        consecutive_unknown_tools = 0

            try:
                self._append_tool_batch(tool_results)
            except SessionError as exc:
                yield AgentEvent(type="error", stop_reason="session_error", message=str(exc))
                yield done_event("session_error", str(exc), iteration, self.config.max_iterations)
                return

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

    def compact(self) -> CompactionReport:
        request = self._last_request or AgentRequest(text="", mode="default")
        registry = self._registry_for_request(request)
        template = self._chat_request_template(request, registry, 1)
        return self.context_manager.compact(template)

    def close(self) -> str | None:
        warnings: list[str] = []
        if self.memory_worker is not None:
            warnings.extend(
                notice.message for notice in self.memory_worker.drain(5.0) if notice.code != "updated"
            )
        if self.session_journal is not None:
            warning = self.session_journal.close()
            if warning:
                warnings.append(warning)
        warning = self.context_manager.close()
        if warning:
            warnings.append(warning)
        return " ".join(warnings) or None

    def new_session(self) -> tuple[str, tuple[str, ...]]:
        warnings: list[str] = []
        if self.memory_worker is not None:
            warnings.extend(
                notice.message for notice in self.memory_worker.drain(5.0) if notice.code != "updated"
            )
        if self.session_journal is not None:
            warning = self.session_journal.close()
            if warning:
                warnings.append(warning)
        warning = self.context_manager.close()
        if warning:
            warnings.append(warning)
        self.session_journal = SessionJournal(self.tool_context.workspace_root)
        self.context_manager = ContextManager(self.context_config, self.provider, self.tool_context.workspace_root)
        self._last_request = None
        self._time_gap_reminder = ""
        return self.session_journal.session_id, tuple(warnings)

    def take_memory_notices(self):
        if self.memory_worker is None:
            return ()
        return self.memory_worker.take_notices()

    def _chat_request_template(self, request: AgentRequest, registry: ToolRegistry, iteration: int) -> ChatRequest:
        environment = EnvironmentInfo(
            cwd=str(self.tool_context.workspace_root),
            date=date.today().isoformat(),
            mode=request.mode,
        )
        prompt = PromptBuilder(repeat_interval=self.config.prompt_repeat_interval).build(
            mode=request.mode,
            iteration=iteration,
            environment=environment,
            options=PromptOptions(
                custom_instructions=self.instruction_bundle.content,
                long_term_memory=self._memory_prompt(),
            ),
        )
        dynamic = [prompt.environment_message, *prompt.dynamic_system_messages]
        if self._time_gap_reminder:
            dynamic.append(DynamicInstruction(tag="mewcode_time_gap", content=self._time_gap_reminder, full=True))
        return ChatRequest(
            stable_system_prompt=prompt.stable_system_prompt,
            dynamic_system_messages=tuple(dynamic),
            messages=(),
            optional_system_prompt=prompt.optional_system_prompt,
            tools=reinforce_tool_specs(registry.tool_specs()),
        )

    def _append_message(self, message: Message) -> None:
        if self.session_journal is not None:
            self.session_journal.append(message)
        if message.role == "user":
            self.context_manager.append_user(message.content)
        elif message.role == "assistant":
            self.context_manager.append_assistant(message.content, message.tool_calls)
        else:
            raise ValueError("工具消息必须按批次追加。")

    def _append_tool_batch(self, results: Sequence[tuple[str, ToolExecutionResult]]) -> None:
        if self.session_journal is not None:
            for tool_call_id, result in results:
                content = json.dumps(asdict(result.complete), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                self.session_journal.append(Message(role="tool", content=content, tool_call_id=tool_call_id))
        self.context_manager.append_tool_batch(results)

    def _memory_prompt(self) -> str:
        if self.memory_store is None:
            return ""
        project = self.memory_store.read_index("project").strip()
        user = self.memory_store.read_index("user").strip()
        sections: list[str] = []
        if project:
            sections.append("### 项目级记忆（高优先级）\n" + project)
        if user:
            sections.append("### 用户级记忆\n" + user)
        return "\n\n".join(sections)

    def _submit_memory(self, user_text: str, assistant_text: str, tool_summaries: Sequence[str]) -> None:
        if self.memory_worker is None or self.session_journal is None:
            return
        self.memory_worker.submit(
            TurnSnapshot(
                session_id=self.session_journal.session_id,
                user_text=user_text[:20_000],
                assistant_text=assistant_text[:20_000],
                tool_summaries=tuple(tool_summaries[:50]),
            )
        )


def _is_unknown_tool_result(result: ToolResult) -> bool:
    return not result.ok and "未知工具" in result.message
