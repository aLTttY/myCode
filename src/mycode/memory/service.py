from __future__ import annotations

import json
import threading
from dataclasses import asdict

from mycode.providers.base import ChatRequest, LLMProvider
from mycode.types import Message, ProviderError

from .models import MemoryNotice, MemoryOperation, TurnSnapshot
from .parser import MemoryFormatError, parse_index_response, parse_memory_response
from .prompts import MEMORY_COMPACT_PROMPT, MEMORY_DECISION_PROMPT, MEMORY_MERGE_PROMPT
from .storage import MemoryStorageError, MemoryStore


class MemoryService:
    def __init__(self, provider: LLMProvider, store: MemoryStore) -> None:
        self.provider = provider
        self.store = store

    def process(self, snapshot: TurnSnapshot, cancelled: threading.Event) -> tuple[MemoryNotice, ...]:
        if cancelled.is_set():
            return (MemoryNotice("cancelled", "自动记忆更新已取消。"),)
        payload = {
            "session_id": snapshot.session_id,
            "user_text": snapshot.user_text,
            "assistant_text": snapshot.assistant_text,
            "tool_summaries": snapshot.tool_summaries,
            "project_index": self.store.read_index("project"),
            "user_index": self.store.read_index("user"),
        }
        try:
            text = self._complete(MEMORY_DECISION_PROMPT, payload)
            decision = parse_memory_response(text, self.store.known_ids())
        except (ProviderError, MemoryFormatError) as exc:
            return (MemoryNotice("decision_failed", _safe_failure("记忆决策", exc)),)
        notices: list[MemoryNotice] = []
        changed_scopes: set[str] = set()
        for operation in decision.operations:
            if cancelled.is_set():
                notices.append(MemoryNotice("cancelled", "自动记忆更新已取消。"))
                break
            if operation.action == "ignore":
                continue
            try:
                candidate = operation
                if operation.action == "update":
                    current = self.store.read_note(operation.scope, operation.target_id)
                    merged_text = self._complete(
                        MEMORY_MERGE_PROMPT,
                        {"current_note": asdict(current), "new_evidence": asdict(operation)},
                    )
                    merged = parse_memory_response(merged_text, self.store.known_ids())
                    if len(merged.operations) != 1 or merged.operations[0].action != "update":
                        raise MemoryFormatError("合并响应必须包含一个 update。")
                    candidate = merged.operations[0]
                    if candidate.target_id != current.id or candidate.scope != current.scope or candidate.category != current.category:
                        raise MemoryFormatError("合并响应改变了目标身份。")
                if cancelled.is_set():
                    notices.append(MemoryNotice("cancelled", "自动记忆更新已取消。"))
                    break
                if candidate.action == "create":
                    self.store.create(candidate, snapshot.session_id)
                else:
                    self.store.update(candidate, snapshot.session_id)
                changed_scopes.add(candidate.scope)
            except (ProviderError, MemoryFormatError, MemoryStorageError) as exc:
                notices.append(MemoryNotice("write_failed", _safe_failure("记忆写入", exc)))
        for scope in changed_scopes:
            if cancelled.is_set() or not self.store.needs_compaction(scope):
                continue
            try:
                notes = self.store.list_notes(scope)
                compact_text = self._complete(
                    MEMORY_COMPACT_PROMPT,
                    {"entries": [{"id": note.id, "summary": note.summary, "importance": note.importance} for note in notes]},
                )
                updates = parse_index_response(compact_text, {note.id for note in notes})
                if not cancelled.is_set():
                    self.store.write_compacted_index(scope, updates)
            except (ProviderError, MemoryFormatError, MemoryStorageError) as exc:
                notices.append(MemoryNotice("compact_failed", _safe_failure("索引精简", exc)))
        if not notices:
            notices.append(MemoryNotice("updated", "自动记忆更新完成。"))
        return tuple(notices)

    def _complete(self, system_prompt: str, payload: object) -> str:
        request = ChatRequest(
            stable_system_prompt=system_prompt,
            dynamic_system_messages=(),
            messages=(Message(role="user", content=json.dumps(payload, ensure_ascii=False, default=str)),),
            tools=(),
            cache_static_content=False,
        )
        parts: list[str] = []
        saw_tool = False
        for event in self.provider.stream_chat(request):
            if event.type == "text_delta":
                parts.append(event.text)
            elif event.type in {"tool_call_delta", "tool_call_done"}:
                saw_tool = True
            elif event.type == "message_done":
                break
        if saw_tool:
            raise MemoryFormatError("记忆模型尝试调用工具。")
        if not parts:
            raise MemoryFormatError("记忆模型返回空响应。")
        return "".join(parts)


def _safe_failure(stage: str, exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return f"{stage} API 调用失败。"
    return str(exc)
