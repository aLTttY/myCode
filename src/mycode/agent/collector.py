from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from mycode.agent.events import AgentEvent
from mycode.types import PendingToolCall, StreamEvent, ToolCall, ToolResult, TokenUsage


@dataclass(frozen=True)
class CollectedResponse:
    assistant_text: str
    tool_calls: tuple[ToolCall, ...]
    parse_errors: tuple[ToolResult, ...]
    token_usage: TokenUsage | None = None


class StreamCollector:
    def collect(self, events: Iterable[StreamEvent]) -> Iterator[AgentEvent | CollectedResponse]:
        assistant_parts: list[str] = []
        pending: dict[str, PendingToolCall] = {}
        order: list[str] = []
        tool_calls: list[ToolCall] = []
        parse_errors: list[ToolResult] = []
        token_usage: TokenUsage | None = None

        for event in events:
            if event.type == "text_delta":
                assistant_parts.append(event.text)
                yield AgentEvent(type="text_delta", text=event.text)
            elif event.type == "tool_call_delta":
                tool_call_id = event.tool_call_id or f"tool_call_{len(order)}"
                if tool_call_id not in pending:
                    pending[tool_call_id] = PendingToolCall(
                        id=tool_call_id,
                        name=event.tool_name,
                        arguments_json_parts=[],
                    )
                    order.append(tool_call_id)
                current = pending[tool_call_id]
                if event.tool_name and not current.name:
                    current.name = event.tool_name
                if event.arguments_delta:
                    current.arguments_json_parts.append(event.arguments_delta)
            elif event.type == "tool_call_done":
                tool_call_id = event.tool_call_id
                if not tool_call_id or tool_call_id not in pending:
                    continue
                current = pending[tool_call_id]
                if event.tool_name and not current.name:
                    current.name = event.tool_name
                call, error = _finalize_pending_call(current)
                if call is not None:
                    tool_calls.append(call)
                if error is not None:
                    parse_errors.append(error)
            elif event.type == "token_usage":
                token_usage = event.token_usage
                yield AgentEvent(type="token_usage", token_usage=token_usage)
            elif event.type == "message_done":
                finalized = {call.id for call in tool_calls}
                finalized.update(str(error.data.get("tool_call_id", "")) for error in parse_errors)
                for tool_call_id in order:
                    if tool_call_id in finalized:
                        continue
                    call, error = _finalize_pending_call(pending[tool_call_id])
                    if call is not None:
                        tool_calls.append(call)
                    if error is not None:
                        parse_errors.append(error)
                yield CollectedResponse(
                    assistant_text="".join(assistant_parts),
                    tool_calls=tuple(tool_calls),
                    parse_errors=tuple(parse_errors),
                    token_usage=token_usage,
                )
                return

        yield CollectedResponse(
            assistant_text="".join(assistant_parts),
            tool_calls=tuple(tool_calls),
            parse_errors=tuple(parse_errors),
            token_usage=token_usage,
        )


def _finalize_pending_call(pending: PendingToolCall) -> tuple[ToolCall | None, ToolResult | None]:
    arguments_json = "".join(pending.arguments_json_parts) or "{}"
    try:
        arguments = json.loads(arguments_json)
    except json.JSONDecodeError as exc:
        return None, ToolResult(
            ok=False,
            message=f"工具参数不是合法 JSON：{exc.msg}",
            data={"tool": pending.name, "tool_call_id": pending.id, "arguments": arguments_json},
        )
    if not isinstance(arguments, dict):
        return None, ToolResult(
            ok=False,
            message="工具参数必须是 JSON 对象。",
            data={"tool": pending.name, "tool_call_id": pending.id, "arguments": arguments},
        )
    if not pending.name:
        return None, ToolResult(
            ok=False,
            message="工具调用缺少工具名称。",
            data={"tool_call_id": pending.id, "arguments": arguments},
        )
    return ToolCall(id=pending.id, name=pending.name, arguments=arguments), None
