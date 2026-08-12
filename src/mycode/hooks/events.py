from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from mycode.context.models import CompactionReport
from mycode.types import ToolCall, ToolExecutionResult

from .models import (
    HookEvent,
    HookEventName,
    HookResultSource,
    HookTurn,
    freeze_json,
)


Clock = Callable[[], datetime]


class HookEventFactory:
    def __init__(self, workspace_root: Path, clock: Clock | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.session_id = ""
        self.session_origin = "new"
        self.turn: HookTurn | None = None

    def set_session(self, session_id: str, origin: str) -> None:
        self.session_id = session_id
        self.session_origin = origin

    def set_turn(self, turn: HookTurn | None) -> None:
        self.turn = turn

    def build(
        self,
        name: HookEventName,
        *,
        end_reason: str = "",
        stop_reason: str = "",
        message_role: str = "",
        message_content: str = "",
        tool_call: ToolCall | None = None,
        tool_result: ToolExecutionResult | None = None,
        result_source: HookResultSource | None = None,
        context_report: CompactionReport | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> HookEvent:
        payload: dict[str, object] = {
            "schema_version": 1,
            "event": name,
            "occurred_at": self.clock().astimezone().isoformat(timespec="microseconds"),
            "workspace": str(self.workspace_root),
            "session": {
                "id": self.session_id,
                "origin": self.session_origin,
            },
        }
        if name == "session_end":
            payload["session"]["end_reason"] = end_reason  # type: ignore[index]
        if self.turn is not None and name not in {"session_start", "session_end"}:
            turn = asdict(self.turn)
            if name == "turn_end":
                turn["stop_reason"] = stop_reason
            payload["turn"] = turn
        if name in {"message_received", "message_sent"}:
            payload["message"] = {"role": message_role, "content": message_content}
        if name in {"tool_before", "tool_after"} and tool_call is not None:
            payload["tool"] = {
                "call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            }
        if name == "tool_after" and tool_result is not None and result_source is not None:
            payload["result"] = {
                **asdict(tool_result.display),
                "source": result_source,
            }
        if name == "context_compacted" and context_report is not None:
            payload["context"] = {
                "trigger": context_report.trigger,
                "before_tokens": context_report.before_tokens,
                "after_tokens": context_report.after_tokens,
                "budget_tokens": context_report.budget_tokens,
                "offloaded_tool_results": context_report.offloaded_tool_results,
                "offloaded_user_messages": context_report.offloaded_user_messages,
                "summarized_messages": context_report.summarized_messages,
            }
        if name == "agent_error":
            payload["error"] = {"code": error_code, "message": error_message}
        return HookEvent(name=name, payload=freeze_json(payload))  # type: ignore[arg-type]
