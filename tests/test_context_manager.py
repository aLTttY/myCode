from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

import mycode.context.manager as manager_module
from mycode.context.manager import BOUNDARY_TAG, SUMMARY_TAG, ContextManager
from mycode.context.models import ContextConfig, SummaryOutput
from mycode.context.prompts import SUMMARY_HEADINGS
from mycode.context.storage import ContextStorageError
from mycode.context.summary import SummaryFailure
from mycode.providers.base import ChatRequest
from mycode.types import Message, ToolCall, ToolExecutionResult, ToolResult


class UnusedProvider:
    def stream_chat(self, request):
        raise AssertionError("普通 Provider 不应由 ContextManager 直接调用")


class SuccessfulSummary:
    def __init__(self) -> None:
        self.calls = []

    def summarize(self, messages, previous_summary="") -> SummaryOutput:
        self.calls.append((tuple(messages), previous_summary))
        text = "\n".join(f"{heading}\n内容" for heading in SUMMARY_HEADINGS)
        return SummaryOutput(summary=text, headings=SUMMARY_HEADINGS)


class FailingSummary:
    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, messages, previous_summary="") -> SummaryOutput:
        self.calls += 1
        raise SummaryFailure("api", "摘要 API 调用失败。")


def template() -> ChatRequest:
    return ChatRequest(
        stable_system_prompt="system",
        dynamic_system_messages=(),
        messages=(),
        tools=(),
    )


def execution(text: str, display_text: str = "shown") -> ToolExecutionResult:
    return ToolExecutionResult(
        display=ToolResult(ok=True, message="ok", data={"content": display_text}),
        complete=ToolResult(ok=True, message="ok", data={"content": text}),
    )


def add_tool_turn(context: ContextManager, *results: tuple[str, ToolExecutionResult]) -> None:
    calls = tuple(ToolCall(id=tool_id, name="read_file", arguments={"path": f"{tool_id}.txt"}) for tool_id, _ in results)
    context.append_assistant("", calls)
    context.append_tool_batch(results)


def configured_manager(
    tmp_path: Path,
    *,
    window: int = 100_000,
    single: int = 8_000,
    batch: int = 16_000,
    summary_service=None,
) -> ContextManager:
    provider = UnusedProvider()
    return ContextManager(
        ContextConfig(window, single, batch),
        provider,
        tmp_path,
        summary_service=summary_service or SuccessfulSummary(),
    )


def test_lightweight_single_result_offloads_complete_content_with_preview(tmp_path: Path) -> None:
    context = configured_manager(tmp_path, single=20, batch=10_000)
    complete_text = "头" * 1_100 + "中间" * 100 + "尾" * 1_100
    add_tool_turn(context, ("call-1", execution(complete_text)))

    prepared = context.prepare_request(template())

    assert prepared.allowed
    assert prepared.report.offloaded_tool_results == 1
    tool_message = prepared.request.messages[-1]
    assert "[工具结果已卸载]" in tool_message.content
    assert "--- preview head ---" in tool_message.content
    assert "--- preview tail ---" in tool_message.content
    path_line = next(line for line in tool_message.content.splitlines() if line.startswith("path: "))
    stored = tmp_path / path_line.removeprefix("path: ")
    assert stored.read_text(encoding="utf-8") == context.store.session_dir.joinpath(stored.name).read_text(encoding="utf-8")
    assert complete_text in stored.read_text(encoding="utf-8")


def test_lightweight_batch_offloads_largest_until_under_limit(tmp_path: Path) -> None:
    context = configured_manager(tmp_path, single=10_000, batch=100)
    add_tool_turn(
        context,
        ("large", execution("a" * 180)),
        ("medium", execution("b" * 90)),
        ("small", execution("c" * 6)),
    )

    prepared = context.prepare_request(template())
    tool_messages = {message.tool_call_id: message.content for message in prepared.request.messages if message.role == "tool"}

    assert prepared.report.offloaded_tool_results == 1
    assert "已卸载" in tool_messages["large"]
    assert "已卸载" not in tool_messages["medium"]
    assert "已卸载" not in tool_messages["small"]


def test_lightweight_storage_failure_keeps_original_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = configured_manager(tmp_path, single=1)
    add_tool_turn(context, ("call-1", execution("secret" * 20)))
    original = context.messages

    def fail_directory():
        raise ContextStorageError("无法写入。")

    monkeypatch.setattr(context.store, "_ensure_session_dir", fail_directory)
    prepared = context.prepare_request(template())

    assert not prepared.allowed
    assert prepared.report.stage == "storage"
    assert context.messages == original
    assert "secret" in context.messages[-1].content


def prepare_heavy_history(context: ContextManager, *, user_text: str = "用户原始目标") -> None:
    context.append_user(user_text)
    for index in range(6):
        context.append_assistant(f"assistant-{index}-" + "x" * 600)


def configure_small_recent_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "AUTO_RESERVE_TOKENS", 500)
    monkeypatch.setattr(manager_module, "MANUAL_RESERVE_TOKENS", 500)
    monkeypatch.setattr(manager_module, "RECENT_TARGET_TOKENS", 100)
    monkeypatch.setattr(manager_module, "RECENT_MIN_MESSAGES", 2)


def test_automatic_summary_runs_once_and_preserves_recent_messages_and_user_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_small_recent_window(monkeypatch)
    summary = SuccessfulSummary()
    context = configured_manager(tmp_path, window=1_400, summary_service=summary)
    prepare_heavy_history(context)

    prepared = context.prepare_request(template())

    assert prepared.allowed
    assert prepared.report.summarized_messages == 5
    assert context.messages[0].content == "用户原始目标"
    assert context.messages[-2].content.startswith("assistant-4-")
    assert context.messages[-1].content.startswith("assistant-5-")
    tags = [message.tag for message in prepared.request.dynamic_system_messages]
    assert tags[-2:] == [SUMMARY_TAG, BOUNDARY_TAG]
    assert "重新读取" in prepared.request.dynamic_system_messages[-1].content
    assert "用户原始目标" in summary.calls[0][0][0].content
    assert len(summary.calls) == 1


def test_recent_boundary_never_splits_tool_call_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manager_module, "AUTO_RESERVE_TOKENS", 200)
    monkeypatch.setattr(manager_module, "RECENT_TARGET_TOKENS", 1)
    monkeypatch.setattr(manager_module, "RECENT_MIN_MESSAGES", 2)
    context = configured_manager(tmp_path, window=1_000, summary_service=SuccessfulSummary())
    context.append_user("goal")
    context.append_assistant("old" + "x" * 3_000)
    add_tool_turn(context, ("call-1", execution("small")))

    prepared = context.prepare_request(template())

    assert prepared.allowed
    assert prepared.request.messages[-2].role == "assistant"
    assert prepared.request.messages[-2].tool_calls[0].id == "call-1"
    assert prepared.request.messages[-1].role == "tool"
    assert prepared.request.messages[-1].tool_call_id == "call-1"


def test_old_user_message_is_offloaded_only_when_needed_for_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_small_recent_window(monkeypatch)
    context = configured_manager(tmp_path, window=1_400, summary_service=SuccessfulSummary())
    original = "用户非常长的原始要求" + "u" * 3_000
    prepare_heavy_history(context, user_text=original)

    prepared = context.prepare_request(template())

    assert prepared.allowed
    assert prepared.report.offloaded_user_messages == 1
    assert "早期用户原始消息已卸载" in context.messages[0].content
    path_line = next(line for line in context.messages[0].content.splitlines() if line.startswith("path: "))
    assert (tmp_path / path_line.removeprefix("path: ")).read_text(encoding="utf-8") == original


def test_summary_failure_rolls_back_history_and_trips_after_three_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_small_recent_window(monkeypatch)
    summary = FailingSummary()
    context = configured_manager(tmp_path, window=1_400, summary_service=summary)
    prepare_heavy_history(context)
    original = context.messages

    reports = [context.prepare_request(template()).report for _ in range(4)]

    assert [report.status for report in reports] == ["failed", "failed", "tripped", "tripped"]
    assert summary.calls == 3
    assert context.messages == original
    assert context.state.automatic_summary_tripped


def test_manual_success_recovers_tripped_automatic_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_small_recent_window(monkeypatch)
    failing = FailingSummary()
    context = configured_manager(tmp_path, window=1_400, summary_service=failing)
    prepare_heavy_history(context)
    for _ in range(3):
        context.prepare_request(template())
    context.summary_service = SuccessfulSummary()

    report = context.compact(template())

    assert report.status == "success"
    assert context.state.consecutive_summary_failures == 0
    assert context.state.automatic_summary_tripped is False


def test_manual_compact_reports_not_needed_without_early_history(tmp_path: Path) -> None:
    context = configured_manager(tmp_path, window=100_000)
    context.append_user("short")

    report = context.compact(template())

    assert report.status == "not_needed"
    assert context.messages == (Message(role="user", content="short"),)
