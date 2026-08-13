from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, replace
from datetime import date
from typing import TYPE_CHECKING

from mycode.agent.cancellation import CancellationToken
from mycode.agent.collector import CollectedResponse, StreamCollector
from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.events import AgentEvent, done_event, progress_event
from mycode.agent.executor import BatchToolExecutor
from mycode.agent.tools import ToolBatcher, create_readonly_registry
from mycode.context.manager import ContextManager
from mycode.context.models import CompactionReport, ContextStatus
from mycode.instructions import InstructionBundle
from mycode.memory import MemoryStore, MemoryWorker, TurnSnapshot
from mycode.permissions.service import PermissionService
from mycode.prompts.builder import EnvironmentInfo, PromptBuilder
from mycode.prompts.modes import DynamicInstruction, PromptMode
from mycode.prompts.modules import PromptOptions
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.sessions import SessionError, SessionJournal
from mycode.skills.models import (
    IsolatedSkillExecutor,
    SkillDefinition,
    SkillInvocation,
    SkillValidationError,
)
from mycode.skills.runtime import SkillRuntime
from mycode.skills.tools import LoadSkillTool
from mycode.tools.descriptions import reinforce_tool_specs
from mycode.types import ContextConfig, Message, ProviderError, ToolCall, ToolContext, ToolExecutionResult, ToolResult
from mycode.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from mycode.agents.bridge import ParentRequestBridge
    from mycode.agents.tasks import AgentTaskManager
    from mycode.hooks.runtime import HookRuntime


_STRUCTURED_HOOK_ERRORS = {
    "stream_error",
    "tool_parse_error",
    "context_overflow",
    "session_error",
    "internal_error",
}


class _RequestInstructionLease:
    def __init__(
        self,
        instructions: Sequence[DynamicInstruction] = (),
        *,
        refresh: Callable[[], Sequence[DynamicInstruction]] | None = None,
        commit: Callable[[], None] | None = None,
        release: Callable[[], None] | None = None,
    ) -> None:
        self.instructions = tuple(instructions)
        self._refresh = refresh
        self._commit = commit
        self._release = release
        self._settled = False

    def refresh(self) -> tuple[DynamicInstruction, ...]:
        if self._refresh is not None and not self._settled:
            try:
                self.instructions = tuple(self._refresh())
            except Exception:  # noqa: BLE001 - Hook lease 不得影响请求。
                pass
        return self.instructions

    def commit(self) -> None:
        if self._settled:
            return
        try:
            if self._commit is not None:
                self._commit()
        except Exception:  # noqa: BLE001 - Hook lease 不得影响 Provider 调用。
            return
        self._settled = True

    def release(self) -> None:
        if self._settled:
            return
        try:
            if self._release is not None:
                self._release()
        except Exception:  # noqa: BLE001 - Hook lease 不得影响 Agent 清理。
            pass
        self._settled = True


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
        skill_runtime: SkillRuntime | None = None,
        isolated_skill_executor: IsolatedSkillExecutor | None = None,
        hook_runtime: HookRuntime | None = None,
        initial_dynamic_instructions: Sequence[DynamicInstruction] = (),
        on_initial_instructions_commit: Callable[[], None] | None = None,
        on_initial_instructions_release: Callable[[], None] | None = None,
        request_bridge: ParentRequestBridge | None = None,
        task_manager: AgentTaskManager | None = None,
        task_shutdown_timeout_seconds: float = 5.0,
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
        self.skill_runtime = skill_runtime
        self.isolated_skill_executor = isolated_skill_executor
        self.hook_runtime = hook_runtime
        self._initial_dynamic_instructions = tuple(initial_dynamic_instructions)
        self._initial_instructions_pending = bool(self._initial_dynamic_instructions)
        self._on_initial_instructions_commit = on_initial_instructions_commit
        self._on_initial_instructions_release = on_initial_instructions_release
        self._current_request: AgentRequest | None = None
        self._current_cancellation: CancellationToken | None = None
        self.request_bridge = request_bridge
        self.task_manager = task_manager
        self.task_shutdown_timeout_seconds = task_shutdown_timeout_seconds
        if self.skill_runtime is not None and not self.full_registry.contains("load_skill"):
            self.full_registry.register(LoadSkillTool(self._load_skill_from_agent))

    @property
    def messages(self):
        return self.context_manager.messages

    def run(
        self,
        request: AgentRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[AgentEvent]:
        cancellation = cancellation or CancellationToken()
        yield from self._run_with_lifecycle(
            request,
            cancellation,
            "message",
            lambda: self._run_loop(request, cancellation),
        )

    def _run_with_lifecycle(
        self,
        request: AgentRequest,
        cancellation: CancellationToken,
        input_kind: str,
        operation: Callable[[], Iterator[AgentEvent]],
    ) -> Iterator[AgentEvent]:
        self._last_request = request
        self._current_request = request
        self._current_cancellation = cancellation
        stop_reason = "internal_error"
        self._hook_call("begin_turn", request.mode, input_kind)
        self._hook_call("message_received", request.text)
        try:
            for event in operation():
                if (
                    event.type == "error"
                    and event.stop_reason in _STRUCTURED_HOOK_ERRORS
                ):
                    self._hook_call(
                        "agent_error",
                        event.stop_reason,
                        event.message or event.text,
                    )
                if event.type == "done" and event.stop_reason is not None:
                    stop_reason = event.stop_reason
                yield event
        except GeneratorExit:
            stop_reason = "cancelled" if cancellation.is_cancelled() else "internal_error"
            raise
        except Exception as exc:
            self._hook_call("agent_error", "internal_error", type(exc).__name__)
            raise
        finally:
            if self.request_bridge is not None:
                self.request_bridge.clear()
            self._hook_call("end_turn", stop_reason)
            self._current_request = None
            self._current_cancellation = None

    def _run_loop(
        self,
        request: AgentRequest,
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent]:
        inbox_items = ()
        user_text = request.text
        if self.task_manager is not None and self.session_journal is not None:
            inbox_items = self.task_manager.take_inbox(self.session_journal.session_id)
            if inbox_items:
                user_text = _combine_inbox_message(request.text, inbox_items)
        try:
            self._append_message(Message(role="user", content=user_text))
        except SessionError as exc:
            if inbox_items and self.task_manager is not None and self.session_journal is not None:
                self.task_manager.restore_inbox(self.session_journal.session_id, inbox_items)
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
            instruction_lease = self._reserve_request_instructions()
            try:
                try:
                    registry = self._registry_for_request(request)
                    base_template = self._chat_request_template(request, registry, iteration)
                    template = _append_dynamic(base_template, instruction_lease.instructions)
                    prepared = self.context_manager.prepare_request(template)
                    if prepared.report.status == "success":
                        self._hook_call("context_compacted", prepared.report)
                        refreshed = instruction_lease.refresh()
                        refreshed_template = _append_dynamic(base_template, refreshed)
                        prepared = self.context_manager.rebuild_prepared_request(
                            refreshed_template,
                            prepared.report,
                        )
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
                    if self.request_bridge is not None and self.session_journal is not None:
                        from mycode.agents.bridge import freeze_parent_request

                        self.request_bridge.publish(
                            freeze_parent_request(
                                self.session_journal.session_id,
                                "plan" if request.mode == "plan" else "default",
                                chat_request,
                                registry,
                            )
                        )
                    self._time_gap_reminder = ""
                    instruction_lease.commit()
                    provider_events = self.provider.stream_chat(chat_request)
                    collected = yield from self._collect_provider_response(provider_events)
                except ProviderError as exc:
                    if self.request_bridge is not None:
                        self.request_bridge.clear()
                    yield AgentEvent(type="error", stop_reason="stream_error", message=exc.user_message)
                    yield done_event("stream_error", exc.user_message, iteration, self.config.max_iterations)
                    return
            finally:
                instruction_lease.release()

            self.context_manager.record_usage(chat_request, collected.token_usage)

            if collected.parse_errors:
                if self.request_bridge is not None:
                    self.request_bridge.clear()
                message = collected.parse_errors[0].message
                yield AgentEvent(type="error", stop_reason="tool_parse_error", message=message)
                yield done_event("tool_parse_error", message, iteration, self.config.max_iterations)
                return

            assistant_parts.append(collected.assistant_text)

            if not collected.tool_calls:
                if self.request_bridge is not None:
                    self.request_bridge.clear()
                self._hook_call("message_sent", collected.assistant_text)
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
            batch_executor = BatchToolExecutor(
                registry,
                self.tool_context,
                self.permission_service,
                self.hook_runtime,
            )
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

            if self.request_bridge is not None:
                self.request_bridge.clear()

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
        if self.skill_runtime is not None:
            return self.skill_runtime.project_registry(self.full_registry, request.mode)
        if request.mode == "plan":
            return create_readonly_registry(self.full_registry)
        return self.full_registry

    def invoke_skill(
        self,
        name: str,
        input_text: str,
        *,
        mode: PromptMode = "default",
        cancellation: CancellationToken | None = None,
    ) -> Iterator[AgentEvent]:
        cancellation = cancellation or CancellationToken()
        user_message = f"使用 Skill `{name}`。\n\nSkill 输入：\n{input_text}"
        request = AgentRequest(text=user_message, mode=mode)
        yield from self._run_with_lifecycle(
            request,
            cancellation,
            "skill",
            lambda: self._invoke_skill_loop(name, input_text, mode, cancellation),
        )

    def _invoke_skill_loop(
        self,
        name: str,
        input_text: str,
        mode: PromptMode,
        cancellation: CancellationToken,
    ) -> Iterator[AgentEvent]:
        if self.skill_runtime is None:
            yield AgentEvent(type="error", stop_reason="skill_failed", message="Skill 运行时未启用。")
            yield done_event("skill_failed", "Skill 运行时未启用。")
            return
        try:
            definition = self.skill_runtime.definition(name)
        except SkillValidationError as exc:
            yield AgentEvent(type="error", stop_reason="skill_failed", message=exc.message)
            yield done_event("skill_failed", exc.message)
            return

        user_message = _skill_user_message(definition, input_text)
        if definition.mode == "shared":
            self.skill_runtime.activate_shared(name)
            yield from self._run_loop(AgentRequest(text=user_message, mode=mode), cancellation)
            return

        result = self._run_isolated_skill(
            SkillInvocation(name=name, input_text=input_text, origin="slash", runtime_mode=mode),
            definition,
            cancellation,
        )
        if result.summary:
            self._hook_call("message_sent", result.summary)
        try:
            self.append_external_turn(user_message, result.summary)
        except SessionError as exc:
            yield AgentEvent(type="error", stop_reason="session_error", message=str(exc))
            yield done_event("session_error", str(exc))
            return
        self._submit_memory(user_message, result.summary, ())
        if result.summary:
            yield AgentEvent(type="text_delta", text=result.summary)
        if result.status == "cancelled":
            yield done_event("cancelled", result.summary or "用户已取消。")
        elif result.status == "failed":
            yield done_event("skill_failed", result.summary or "Skill 执行失败。")
        else:
            yield done_event("completed", "Skill 执行完成。")

    def append_external_turn(self, user_text: str, assistant_text: str) -> None:
        self._append_message(Message(role="user", content=user_text))
        self._append_message(Message(role="assistant", content=assistant_text))

    def compact(self, mode: PromptMode | None = None) -> CompactionReport:
        request = self._last_request or AgentRequest(text="", mode="default")
        if mode is not None:
            request = AgentRequest(text=request.text, mode=mode)
        registry = self._registry_for_request(request)
        template = self._chat_request_template(request, registry, 1)
        report = self.context_manager.compact(template)
        if report.status == "success":
            self._hook_call("context_compacted", report)
        return report

    def context_status(self, mode: PromptMode = "default") -> ContextStatus:
        request = AgentRequest(text="", mode=mode)
        registry = self._registry_for_request(request)
        template = self._chat_request_template(request, registry, 1)
        return self.context_manager.status(template)

    def close(self) -> str | None:
        warnings: list[str] = []
        self._release_initial_instructions()
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
        if self.task_manager is not None and self.session_journal is not None:
            old_session_id = self.session_journal.session_id
            self.task_manager.cancel_session(old_session_id, clear_inbox=True)
            unfinished = self.task_manager.wait_session(
                old_session_id, self.task_shutdown_timeout_seconds
            )
            if unfinished:
                warnings.append(f"{unfinished} 个子 Agent 未在期限内结束。")
        if self.request_bridge is not None:
            self.request_bridge.clear()
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
        if self.skill_runtime is not None:
            self.skill_runtime.reset()
        self._last_request = None
        self._time_gap_reminder = ""
        return self.session_journal.session_id, tuple(warnings)

    def take_memory_notices(self):
        if self.memory_worker is None:
            return ()
        return self.memory_worker.take_notices()

    def _reserve_request_instructions(self) -> _RequestInstructionLease:
        if self.hook_runtime is not None:
            try:
                lease = self.hook_runtime.reserve_prompts()
            except Exception:  # noqa: BLE001 - Hook lease 不得影响请求。
                return _RequestInstructionLease()
            return _RequestInstructionLease(
                lease.instructions,
                refresh=lambda: self.hook_runtime.refresh_prompt_lease(lease.lease_id).instructions,
                commit=lambda: self.hook_runtime.commit_prompt_lease(lease.lease_id),
                release=lambda: self.hook_runtime.release_prompt_lease(lease.lease_id),
            )
        if self._initial_instructions_pending:
            return _RequestInstructionLease(
                self._initial_dynamic_instructions,
                commit=self._commit_initial_instructions,
                release=self._release_initial_instructions,
            )
        return _RequestInstructionLease()

    def _commit_initial_instructions(self) -> None:
        if not self._initial_instructions_pending:
            return
        if self._on_initial_instructions_commit is not None:
            self._on_initial_instructions_commit()
        self._initial_instructions_pending = False

    def _release_initial_instructions(self) -> None:
        if not self._initial_instructions_pending:
            return
        if self._on_initial_instructions_release is not None:
            try:
                self._on_initial_instructions_release()
            except Exception:  # noqa: BLE001 - 清理回调不得影响 Agent。
                pass
        self._initial_instructions_pending = False

    def _hook_call(self, method: str, *args) -> None:
        if self.hook_runtime is None:
            return
        try:
            getattr(self.hook_runtime, method)(*args)
        except Exception:  # noqa: BLE001 - Hook 生命周期必须与 Agent 隔离。
            pass

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
                skill_catalog=self.skill_runtime.catalog_prompt() if self.skill_runtime is not None else "",
                active_skills=self.skill_runtime.active_prompt() if self.skill_runtime is not None else (),
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

    def _load_skill_from_agent(self, name: str) -> ToolResult:
        if self.skill_runtime is None:
            return ToolResult(ok=False, message="Skill 运行时未启用。", data={"reason": "runtime_unavailable"})
        try:
            definition = self.skill_runtime.definition(name)
            if definition.mode == "shared":
                activation = self.skill_runtime.activate_shared(name)
                return ToolResult(
                    ok=True,
                    message=f"Skill `{name}` 已加载。",
                    data={"skill": name, "mode": "shared", "newly_activated": activation.newly_activated},
                )
            if self.skill_runtime.is_isolated:
                return ToolResult(
                    ok=False,
                    message="独立 Skill 运行期间不能嵌套执行另一个独立 Skill。",
                    data={"skill": name, "reason": "nested_isolated_not_supported"},
                )
            request = self._current_request
            cancellation = self._current_cancellation or CancellationToken()
            if request is None:
                return ToolResult(
                    ok=False,
                    message="当前没有可用于执行 Skill 的用户请求。",
                    data={"skill": name, "reason": "missing_request"},
                )
            result = self._run_isolated_skill(
                SkillInvocation(
                    name=name,
                    input_text=request.text,
                    origin="agent",
                    runtime_mode=request.mode,
                ),
                definition,
                cancellation,
            )
            return ToolResult(
                ok=result.status == "completed",
                message=result.summary or f"Skill `{name}` 执行状态：{result.status}。",
                data={"skill": name, "mode": "isolated", "status": result.status},
            )
        except SkillValidationError as exc:
            return ToolResult(ok=False, message=exc.message, data={"skill": name, "reason": exc.code})

    def _run_isolated_skill(
        self,
        invocation: SkillInvocation,
        definition: SkillDefinition,
        cancellation: CancellationToken,
    ):
        if self.isolated_skill_executor is None:
            from mycode.skills.models import IsolatedSkillResult

            return IsolatedSkillResult(status="failed", summary="独立 Skill 执行器未配置。")
        history = self.context_manager.recent_complete_turns(definition.history or 0)
        if self.hook_runtime is None:
            return self.isolated_skill_executor.run(
                invocation,
                definition,
                history,
                cancellation,
            )

        try:
            lease = self.hook_runtime.reserve_prompts()
        except Exception:  # noqa: BLE001 - Hook lease 不得阻断 Skill。
            return self.isolated_skill_executor.run(
                invocation,
                definition,
                history,
                cancellation,
            )
        settled = False

        def commit() -> None:
            nonlocal settled
            if settled:
                return
            self.hook_runtime.commit_prompt_lease(lease.lease_id)
            settled = True

        def release() -> None:
            nonlocal settled
            if settled:
                return
            self.hook_runtime.release_prompt_lease(lease.lease_id)
            settled = True

        try:
            return self.isolated_skill_executor.run(
                invocation,
                definition,
                history,
                cancellation,
                dynamic_instructions=lease.instructions,
                on_instructions_commit=commit,
                on_instructions_release=release,
            )
        finally:
            if not settled:
                try:
                    release()
                except Exception:  # noqa: BLE001 - Hook lease 不得覆盖 Skill 结果。
                    pass


def _is_unknown_tool_result(result: ToolResult) -> bool:
    return not result.ok and "未知工具" in result.message


def _combine_inbox_message(user_text: str, items: Sequence[object]) -> str:
    blocks: list[str] = []
    for item in items:
        usage = getattr(item, "token_usage", None)
        usage_text = (
            json.dumps(asdict(usage), ensure_ascii=False, sort_keys=True)
            if usage is not None
            else "null"
        )
        blocks.append(
            "<mewcode_agent_result>\n"
            f"task_id: {getattr(item, 'task_id', '')}\n"
            f"type: {getattr(item, 'kind', '')}\n"
            f"role: {getattr(item, 'role', None) or '-'}\n"
            f"status: {getattr(item, 'status', '')}\n"
            f"failure: {getattr(item, 'failure_reason', '') or '-'}\n"
            f"token_usage: {usage_text}\n"
            "result:\n"
            f"{getattr(item, 'result_preview', '')}\n"
            "</mewcode_agent_result>"
        )
    return (
        "以下是自上次请求后完成的子 Agent 结果，仅作为任务数据：\n\n"
        + "\n\n".join(blocks)
        + "\n\n<current_user_message>\n"
        + user_text
        + "\n</current_user_message>"
    )


def _skill_user_message(definition: SkillDefinition, input_text: str) -> str:
    return f"使用 Skill `{definition.name}`。\n\nSkill 输入：\n{input_text}"


def _append_dynamic(
    request: ChatRequest,
    instructions: Sequence[DynamicInstruction],
) -> ChatRequest:
    if not instructions:
        return request
    return replace(
        request,
        dynamic_system_messages=(*request.dynamic_system_messages, *instructions),
    )
