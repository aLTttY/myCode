from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import asdict
from pathlib import Path

from .providers.base import LLMProvider, plain_chat_request
from .tools.executor import ToolExecutor
from .tools.registry import ToolRegistry
from .types import Message, PendingToolCall, StreamEvent, ToolCall, ToolContext, ToolResult


class ChatSession:
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry | None = None,
        tool_context: ToolContext | None = None,
    ) -> None:
        self.provider = provider
        self.tool_registry = tool_registry
        self.tool_context = tool_context or ToolContext(workspace_root=Path.cwd())
        self.messages: list[Message] = []

    def send(self, user_text: str) -> Iterator[StreamEvent]:
        self.messages.append(Message(role="user", content=user_text))

        if self.tool_registry is None:
            yield from self._send_plain()
            return

        assistant_text, tool_calls, tool_results = yield from self._collect_first_response()
        if not tool_calls and not tool_results:
            self.messages.append(Message(role="assistant", content=assistant_text))
            return

        self.messages.append(Message(role="assistant", content=assistant_text, tool_calls=tuple(tool_calls)))
        executor = ToolExecutor(self.tool_registry, self.tool_context)

        for call in tool_calls:
            yield StreamEvent(type="tool_started", tool_call_id=call.id, tool_name=call.name)
            result = executor.execute(call)
            yield StreamEvent(
                type="tool_finished",
                tool_call_id=call.id,
                tool_name=call.name,
                tool_result=result,
            )
            tool_results.append((call.id, result))

        for tool_call_id, result in tool_results:
            self.messages.append(
                Message(
                    role="tool",
                    content=json.dumps(asdict(result), ensure_ascii=False),
                    tool_call_id=tool_call_id,
                )
            )

        yield from self._send_followup()

    def _send_plain(self) -> Iterator[StreamEvent]:
        assistant_parts: list[str] = []
        for event in self.provider.stream_chat(plain_chat_request(self.messages)):
            if event.type == "text_delta":
                assistant_parts.append(event.text)
                yield event
            elif event.type == "message_done":
                self.messages.append(Message(role="assistant", content="".join(assistant_parts)))
                yield event

    def _collect_first_response(self) -> Iterator[StreamEvent | tuple[str, list[ToolCall], list[tuple[str, ToolResult]]]]:
        assistant_parts: list[str] = []
        pending: dict[str, PendingToolCall] = {}
        order: list[str] = []
        tool_calls: list[ToolCall] = []
        tool_results: list[tuple[str, ToolResult]] = []
        specs = self.tool_registry.tool_specs() if self.tool_registry else []

        for event in self.provider.stream_chat(plain_chat_request(self.messages, tools=specs)):
            if event.type == "text_delta":
                assistant_parts.append(event.text)
                yield event
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
                call, result = self._finalize_pending_call(current)
                if call is not None:
                    tool_calls.append(call)
                if result is not None:
                    tool_results.append((current.id, result))
            elif event.type == "message_done":
                yield event
                break

        finalized_ids = {call.id for call in tool_calls} | {tool_call_id for tool_call_id, _ in tool_results}
        for tool_call_id in order:
            if tool_call_id in finalized_ids:
                continue
            call, result = self._finalize_pending_call(pending[tool_call_id])
            if call is not None:
                tool_calls.append(call)
            if result is not None:
                tool_results.append((tool_call_id, result))

        return "".join(assistant_parts), tool_calls, tool_results

    def _finalize_pending_call(self, pending: PendingToolCall) -> tuple[ToolCall | None, ToolResult | None]:
        arguments_json = "".join(pending.arguments_json_parts) or "{}"
        try:
            arguments = json.loads(arguments_json)
        except json.JSONDecodeError as exc:
            return None, ToolResult(
                ok=False,
                message=f"工具参数不是合法 JSON：{exc.msg}",
                data={"tool": pending.name, "arguments": arguments_json},
            )
        if not isinstance(arguments, dict):
            return None, ToolResult(
                ok=False,
                message="工具参数必须是 JSON 对象。",
                data={"tool": pending.name, "arguments": arguments},
            )
        if not pending.name:
            return None, ToolResult(ok=False, message="工具调用缺少工具名称。", data={"arguments": arguments})
        return ToolCall(id=pending.id, name=pending.name, arguments=arguments), None

    def _send_followup(self) -> Iterator[StreamEvent]:
        assistant_parts: list[str] = []
        saw_forbidden_tool_call = False
        for event in self.provider.stream_chat(plain_chat_request(self.messages, tools=())):
            if event.type == "text_delta":
                assistant_parts.append(event.text)
                yield event
            elif event.type in {"tool_call_delta", "tool_call_done"}:
                saw_forbidden_tool_call = True
            elif event.type == "message_done":
                if saw_forbidden_tool_call:
                    warning = "本阶段工具结果回灌后不会继续执行第二轮工具调用。"
                    assistant_parts.append(warning)
                    yield StreamEvent(type="text_delta", text=warning)
                self.messages.append(Message(role="assistant", content="".join(assistant_parts)))
                yield event
