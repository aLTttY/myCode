from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Sequence

from mycode.prompts.modes import DynamicInstruction
from mycode.providers.base import ChatRequest, LLMProvider
from mycode.types import Message, TokenUsage, ToolCall, ToolExecutionResult

from .estimator import TokenEstimator, approximate_tokens
from .models import (
    AUTO_RESERVE_TOKENS,
    MANUAL_RESERVE_TOKENS,
    MAX_SUMMARY_FAILURES,
    PREVIEW_CHARS,
    RECENT_MIN_MESSAGES,
    RECENT_TARGET_TOKENS,
    CompactionReport,
    CompactionTrigger,
    ContextConfig,
    ContextState,
    ContextUnit,
    ManagedMessage,
    PreparedContext,
)
from .prompts import CONTEXT_BOUNDARY_PROMPT
from .storage import ContextStorageError, ContextStore
from .summary import SummaryFailure, SummaryService


SUMMARY_TAG = "mewcode_context_summary"
BOUNDARY_TAG = "mewcode_context_boundary"


class ContextManager:
    def __init__(
        self,
        config: ContextConfig,
        provider: LLMProvider,
        workspace_root: Path,
        *,
        estimator: TokenEstimator | None = None,
        store: ContextStore | None = None,
        summary_service: SummaryService | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.estimator = estimator or TokenEstimator()
        self.store = store or ContextStore(workspace_root)
        self.summary_service = summary_service or SummaryService(provider)
        self._entries: tuple[ManagedMessage, ...] = ()
        self._state = ContextState()
        self._next_sequence = 1
        self._next_batch = 1

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(entry.message for entry in self._entries)

    @property
    def state(self) -> ContextState:
        return self._state

    def append_user(self, content: str) -> None:
        self._append(ManagedMessage(sequence=self._take_sequence(), message=Message(role="user", content=content)))

    def append_assistant(self, content: str, tool_calls: Sequence[ToolCall] = ()) -> None:
        self._append(
            ManagedMessage(
                sequence=self._take_sequence(),
                message=Message(role="assistant", content=content, tool_calls=tuple(tool_calls)),
            )
        )

    def append_tool_batch(
        self,
        results: Sequence[tuple[str, ToolExecutionResult]],
    ) -> None:
        batch_id = f"batch-{self._next_batch}"
        self._next_batch += 1
        entries = list(self._entries)
        for tool_call_id, result in results:
            content = json.dumps(
                asdict(result.complete),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            entries.append(
                ManagedMessage(
                    sequence=self._take_sequence(),
                    message=Message(role="tool", content=content, tool_call_id=tool_call_id),
                    complete_content=content,
                    batch_id=batch_id,
                    source_id=tool_call_id,
                )
            )
        self._set_entries(tuple(entries))

    def prepare_request(
        self,
        template: ChatRequest,
        *,
        trigger: CompactionTrigger = "automatic",
    ) -> PreparedContext:
        budget = self.config.window_tokens - (
            AUTO_RESERVE_TOKENS if trigger == "automatic" else MANUAL_RESERVE_TOKENS
        )
        original_request = self._build_request(template, self._entries, self._state.summary, self._state.boundary)
        before = self.estimator.estimate(original_request)
        transaction = self.store.begin()
        candidate = list(self._entries)
        try:
            offloaded_tools = self._apply_lightweight(candidate, transaction)
        except ContextStorageError as exc:
            transaction.rollback()
            report = self._report("failed", trigger, before, before, budget, stage="storage", reason=str(exc))
            return PreparedContext(False, original_request, report)

        light_request = self._build_request(template, candidate, self._state.summary, self._state.boundary)
        light_tokens = self.estimator.estimate(light_request)
        needs_summary = trigger == "manual" or light_tokens >= budget

        if not needs_summary:
            transaction.commit()
            self._commit_entries(candidate, summary=self._state.summary, boundary=self._state.boundary)
            status = "success" if offloaded_tools else "not_needed"
            report = self._report(
                status,
                trigger,
                before,
                light_tokens,
                budget,
                offloaded_tool_results=offloaded_tools,
            )
            return PreparedContext(True, light_request, report)

        if trigger == "automatic" and self._state.automatic_summary_tripped:
            transaction.rollback()
            report = self._report(
                "tripped",
                trigger,
                before,
                before,
                budget,
                stage="breaker",
                reason="自动摘要已熔断，请执行 /compact 主动重试。",
            )
            return PreparedContext(False, original_request, report)

        units = self._build_units(candidate)
        early, recent = self._split_for_summary(units)
        if not early:
            if trigger == "manual" and before < budget:
                transaction.commit()
                self._commit_entries(candidate, summary=self._state.summary, boundary=self._state.boundary)
                status = "success" if offloaded_tools else "not_needed"
                report = self._report(
                    status,
                    trigger,
                    before,
                    light_tokens,
                    budget,
                    offloaded_tool_results=offloaded_tools,
                )
                return PreparedContext(True, light_request, report)
            transaction.rollback()
            return self._summary_failure(
                trigger,
                original_request,
                before,
                budget,
                "selection",
                "没有可压缩的早期历史。",
            )

        early_messages = tuple(message for unit in early for message in unit.messages)
        try:
            summary = self.summary_service.summarize(early_messages, self._state.summary)
            early_entry_count = sum(unit.message_count for unit in early)
            early_entries = candidate[:early_entry_count]
            recent_entries = candidate[early_entry_count:]
            early_sequences = {entry.sequence for entry in early_entries}
            preserved_users = [
                entry
                for entry in early_entries
                if entry.message.role == "user"
            ]
            summarized_candidate = preserved_users + recent_entries
            summary_text = summary.summary
            boundary = CONTEXT_BOUNDARY_PROMPT
            final_request = self._build_request(template, summarized_candidate, summary_text, boundary)
            final_tokens = self.estimator.estimate(final_request)
            offloaded_users = 0
            for index, entry in enumerate(list(summarized_candidate)):
                if final_tokens < budget:
                    break
                if entry.sequence not in early_sequences or entry.message.role != "user" or entry.offloaded:
                    continue
                reference = transaction.write_user_message(str(entry.sequence), entry.message.content)
                replacement = replace(
                    entry,
                    message=Message(
                        role="user",
                        content=(
                            "[早期用户原始消息已卸载]\n"
                            f"path: {reference.path}\n"
                            f"original_chars: {reference.original_chars}\n"
                            "需要原始要求时必须重新读取该文件，不得根据摘要改写或猜测。"
                        ),
                    ),
                    complete_content="",
                    offloaded=True,
                )
                summarized_candidate[index] = replacement
                offloaded_users += 1
                final_request = self._build_request(template, summarized_candidate, summary_text, boundary)
                final_tokens = self.estimator.estimate(final_request)
            if final_tokens >= budget or (trigger == "manual" and final_tokens >= before):
                raise SummaryFailure("budget", "压缩后仍未达到目标预算。")
        except (SummaryFailure, ContextStorageError) as exc:
            transaction.rollback()
            stage = exc.stage if isinstance(exc, SummaryFailure) else "storage"
            return self._summary_failure(trigger, original_request, before, budget, stage, str(exc))

        transaction.commit()
        self._entries = tuple(summarized_candidate)
        self._state = ContextState(
            messages=self.messages,
            summary=summary_text,
            boundary=boundary,
            consecutive_summary_failures=0,
            automatic_summary_tripped=False,
            token_anchor=self.estimator.anchor,
        )
        report = self._report(
            "success",
            trigger,
            before,
            final_tokens,
            budget,
            offloaded_tool_results=offloaded_tools,
            offloaded_user_messages=offloaded_users,
            summarized_messages=len(early_messages),
        )
        return PreparedContext(True, final_request, report)

    def compact(self, template: ChatRequest) -> CompactionReport:
        return self.prepare_request(template, trigger="manual").report

    def record_usage(self, request: ChatRequest, usage: TokenUsage | None) -> None:
        if self.estimator.record_usage(request, usage):
            self._state = replace(self._state, token_anchor=self.estimator.anchor)

    def close(self) -> str | None:
        return self.store.close()

    def _apply_lightweight(self, entries: list[ManagedMessage], transaction) -> int:
        offloaded = 0
        for index, entry in enumerate(list(entries)):
            if not self._is_inline_tool_result(entry):
                continue
            if approximate_tokens(entry.complete_content) > self.config.tool_result_threshold_tokens:
                entries[index] = self._offload_tool(entry, transaction)
                offloaded += 1

        batch_ids = tuple(dict.fromkeys(entry.batch_id for entry in entries if entry.batch_id))
        for batch_id in batch_ids:
            candidates = [
                (index, entry, approximate_tokens(entry.complete_content))
                for index, entry in enumerate(entries)
                if entry.batch_id == batch_id and self._is_inline_tool_result(entry)
            ]
            total = sum(size for _, _, size in candidates)
            for index, entry, size in sorted(candidates, key=lambda item: item[2], reverse=True):
                if total <= self.config.tool_batch_threshold_tokens:
                    break
                entries[index] = self._offload_tool(entry, transaction)
                total -= size
                offloaded += 1
        return offloaded

    def _offload_tool(self, entry: ManagedMessage, transaction) -> ManagedMessage:
        reference = transaction.write_tool_result(entry.source_id, entry.complete_content)
        content = entry.complete_content
        head = content[:PREVIEW_CHARS]
        tail = content[-PREVIEW_CHARS:]
        preview = (
            "[工具结果已卸载]\n"
            f"path: {reference.path}\n"
            f"original_chars: {reference.original_chars}\n"
            f"approximate_tokens: {reference.approximate_tokens}\n"
            "需要完整细节时必须重新读取该文件。\n"
            "--- preview head ---\n"
            f"{head}\n"
            "--- preview tail ---\n"
            f"{tail}"
        )
        return replace(
            entry,
            message=replace(entry.message, content=preview),
            complete_content="",
            offloaded=True,
        )

    def _build_units(self, entries: Sequence[ManagedMessage]) -> tuple[ContextUnit, ...]:
        units: list[ContextUnit] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            messages = [entry.message]
            index += 1
            if entry.message.role == "assistant" and entry.message.tool_calls:
                expected = {call.id for call in entry.message.tool_calls}
                while index < len(entries):
                    following = entries[index]
                    if following.message.role != "tool" or following.message.tool_call_id not in expected:
                        break
                    messages.append(following.message)
                    index += 1
            units.append(ContextUnit(messages=tuple(messages)))
        return tuple(units)

    def _split_for_summary(
        self,
        units: Sequence[ContextUnit],
    ) -> tuple[tuple[ContextUnit, ...], tuple[ContextUnit, ...]]:
        tokens = 0
        message_count = 0
        split = len(units)
        for index in range(len(units) - 1, -1, -1):
            unit = units[index]
            tokens += sum(self._message_tokens(message) for message in unit.messages)
            message_count += unit.message_count
            split = index
            if tokens >= RECENT_TARGET_TOKENS and message_count >= RECENT_MIN_MESSAGES:
                break
        return tuple(units[:split]), tuple(units[split:])

    def _build_request(
        self,
        template: ChatRequest,
        entries: Sequence[ManagedMessage],
        summary: str,
        boundary: str,
    ) -> ChatRequest:
        dynamic = list(template.dynamic_system_messages)
        if summary:
            dynamic.append(DynamicInstruction(tag=SUMMARY_TAG, content=summary, full=True))
        if boundary:
            dynamic.append(DynamicInstruction(tag=BOUNDARY_TAG, content=boundary, full=True))
        return replace(
            template,
            dynamic_system_messages=tuple(dynamic),
            messages=tuple(entry.message for entry in entries),
        )

    def _summary_failure(
        self,
        trigger: CompactionTrigger,
        request: ChatRequest,
        before: int,
        budget: int,
        stage: str,
        reason: str,
    ) -> PreparedContext:
        failures = self._state.consecutive_summary_failures + 1
        tripped = failures >= MAX_SUMMARY_FAILURES
        self._state = replace(
            self._state,
            consecutive_summary_failures=failures,
            automatic_summary_tripped=tripped,
        )
        report = self._report(
            "tripped" if tripped else "failed",
            trigger,
            before,
            before,
            budget,
            stage=stage,
            reason=reason,
        )
        return PreparedContext(False, request, report)

    def _commit_entries(self, entries: Sequence[ManagedMessage], summary: str, boundary: str) -> None:
        self._entries = tuple(entries)
        self._state = replace(
            self._state,
            messages=self.messages,
            summary=summary,
            boundary=boundary,
            token_anchor=self.estimator.anchor,
        )

    def _set_entries(self, entries: tuple[ManagedMessage, ...]) -> None:
        self._entries = entries
        self._state = replace(self._state, messages=self.messages)

    def _append(self, entry: ManagedMessage) -> None:
        self._set_entries((*self._entries, entry))

    def _take_sequence(self) -> int:
        value = self._next_sequence
        self._next_sequence += 1
        return value

    @staticmethod
    def _is_inline_tool_result(entry: ManagedMessage) -> bool:
        return entry.message.role == "tool" and bool(entry.complete_content) and not entry.offloaded

    @staticmethod
    def _message_tokens(message: Message) -> int:
        return approximate_tokens(
            json.dumps(asdict(message), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )

    @staticmethod
    def _report(
        status,
        trigger,
        before,
        after,
        budget,
        *,
        offloaded_tool_results=0,
        offloaded_user_messages=0,
        summarized_messages=0,
        stage="",
        reason="",
    ) -> CompactionReport:
        return CompactionReport(
            status=status,
            trigger=trigger,
            before_tokens=before,
            after_tokens=after,
            budget_tokens=budget,
            offloaded_tool_results=offloaded_tool_results,
            offloaded_user_messages=offloaded_user_messages,
            summarized_messages=summarized_messages,
            stage=stage,
            reason=reason,
        )
