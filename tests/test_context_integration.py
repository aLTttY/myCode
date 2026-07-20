from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

import mycode.context.manager as manager_module
from mycode.agent.config import AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.context.manager import BOUNDARY_TAG, SUMMARY_TAG, ContextManager
from mycode.context.models import ContextConfig, SummaryOutput
from mycode.context.prompts import SUMMARY_HEADINGS
from mycode.context.summary import SummaryFailure
from mycode.permissions.service import PermissionService
from mycode.providers.base import ChatRequest
from mycode.tools.files import ReadFileTool
from mycode.tools.registry import ToolRegistry
from mycode.types import (
    StreamEvent,
    ToolContext,
    ToolExecutionResult,
    ToolResult,
    ToolSpec,
)


def valid_summary() -> str:
    body = "\n".join(f"{heading}\n保持已知事实和路径" for heading in SUMMARY_HEADINGS)
    return f"<analysis_draft>discard me</analysis_draft><final_summary>\n{body}\n</final_summary>"


class LargeReadTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="scripted large read",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolExecutionResult:
        path = str(arguments["path"])
        sizes = {"large.txt": 12_000, "medium.txt": 2_400, "small.txt": 2_400}
        content = path[0] * sizes[path]
        return ToolExecutionResult(
            display=ToolResult(ok=True, message="shown", data={"content": content[:20]}),
            complete=ToolResult(ok=True, message="complete", data={"path": path, "content": content}),
        )


class LongSessionProvider:
    def __init__(self) -> None:
        self.ordinary_requests: list[ChatRequest] = []
        self.summary_requests: list[ChatRequest] = []

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamEvent]:
        if "内部上下文摘要器" in request.stable_system_prompt:
            self.summary_requests.append(request)
            yield StreamEvent(type="text_delta", text=valid_summary())
            yield StreamEvent(type="message_done")
            return

        self.ordinary_requests.append(request)
        index = len(self.ordinary_requests)
        if index == 1:
            for call_index, path in enumerate(("large.txt", "medium.txt", "small.txt"), start=1):
                yield StreamEvent(
                    type="tool_call_delta",
                    tool_call_id=str(call_index),
                    tool_name="read_file",
                    arguments_delta=f'{{"path":"{path}"}}',
                )
                yield StreamEvent(type="tool_call_done", tool_call_id=str(call_index))
            yield StreamEvent(type="message_done")
            return
        if index == 2:
            text = "first tool turn complete"
        elif index == 3:
            text = "A" * 5_000
        elif index == 4:
            text = "B" * 5_000
        else:
            text = "continued after compaction"
        yield StreamEvent(type="text_delta", text=text)
        yield StreamEvent(type="message_done")


def test_long_session_offloads_summarizes_rereads_and_cleans_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(manager_module, "AUTO_RESERVE_TOKENS", 1_000)
    monkeypatch.setattr(manager_module, "RECENT_TARGET_TOKENS", 300)
    monkeypatch.setattr(manager_module, "RECENT_MIN_MESSAGES", 2)
    provider = LongSessionProvider()
    registry = ToolRegistry()
    registry.register(LargeReadTool())
    agent = AgentRunner(
        provider,
        registry,
        ToolContext(workspace_root=tmp_path),
        permission_service=PermissionService.with_mode("allow"),
        context_config=ContextConfig(
            window_tokens=6_000,
            tool_result_threshold_tokens=1_000,
            tool_batch_threshold_tokens=1_300,
        ),
    )

    assert list(agent.run(AgentRequest("start")))[-1].stop_reason == "completed"
    tool_request = provider.ordinary_requests[1]
    tool_messages = [message for message in tool_request.messages if message.role == "tool"]
    assert sum("工具结果已卸载" in message.content for message in tool_messages) == 2
    path_line = next(
        line
        for message in tool_messages
        for line in message.content.splitlines()
        if line.startswith("path: ")
    )
    relative_path = path_line.removeprefix("path: ")
    read_back = ReadFileTool().run(
        {"path": relative_path},
        ToolContext(workspace_root=tmp_path, max_output_chars=100_000),
    )
    assert read_back.ok
    assert len(read_back.data["content"]) > 10_000

    assert list(agent.run(AgentRequest("second")))[-1].stop_reason == "completed"
    assert list(agent.run(AgentRequest("third")))[-1].stop_reason == "completed"
    final_events = list(agent.run(AgentRequest("fourth")))

    assert final_events[-1].stop_reason == "completed"
    assert len(provider.summary_requests) == 1
    final_request = provider.ordinary_requests[-1]
    tags = [item.tag for item in final_request.dynamic_system_messages]
    assert SUMMARY_TAG in tags and BOUNDARY_TAG in tags
    assert all("discard me" not in item.render() for item in final_request.dynamic_system_messages)
    assert any(message.content == "fourth" for message in final_request.messages)
    session_dir = agent.context_manager.store.session_dir
    assert session_dir.exists()

    assert agent.close() is None
    assert not session_dir.exists()


class AlwaysFailSummary:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, messages, previous_summary=""):
        self.calls += 1
        raise SummaryFailure("api", "摘要 API 调用失败。")


class RecoverSummary:
    def summarize(self, messages, previous_summary=""):
        body = "\n".join(f"{heading}\n恢复" for heading in SUMMARY_HEADINGS)
        return SummaryOutput(summary=body, headings=SUMMARY_HEADINGS)


def test_breaker_recovery_requires_successful_manual_compact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(manager_module, "AUTO_RESERVE_TOKENS", 500)
    monkeypatch.setattr(manager_module, "MANUAL_RESERVE_TOKENS", 500)
    monkeypatch.setattr(manager_module, "RECENT_TARGET_TOKENS", 100)
    monkeypatch.setattr(manager_module, "RECENT_MIN_MESSAGES", 2)
    provider = LongSessionProvider()
    failing = AlwaysFailSummary()
    context = ContextManager(
        ContextConfig(window_tokens=1_400),
        provider,
        tmp_path,
        summary_service=failing,
    )
    context.append_user("sensitive goal")
    for index in range(6):
        context.append_assistant(f"old-{index}-" + "x" * 600)
    request = ChatRequest("system", (), (), tools=())

    reports = [context.prepare_request(request).report for _ in range(4)]

    assert [report.status for report in reports] == ["failed", "failed", "tripped", "tripped"]
    assert failing.calls == 3
    context.summary_service = RecoverSummary()
    manual = context.compact(request)
    assert manual.status == "success"
    assert context.state.automatic_summary_tripped is False
    assert context.state.consecutive_summary_failures == 0
