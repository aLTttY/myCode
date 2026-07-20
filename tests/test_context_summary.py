from __future__ import annotations

from collections.abc import Iterator

import pytest

from mycode.context.prompts import SUMMARY_HEADINGS, SUMMARY_SYSTEM_PROMPT
from mycode.context.summary import SummaryFailure, SummaryService, parse_summary_response
from mycode.providers.base import ChatRequest
from mycode.types import Message, ProviderError, StreamEvent


def valid_response() -> str:
    body = "\n".join(f"{heading}\n内容" for heading in SUMMARY_HEADINGS)
    return f"<analysis_draft>临时分析</analysis_draft><final_summary>\n{body}\n</final_summary>"


class ScriptedProvider:
    def __init__(self, events: list[StreamEvent] | None = None, error: bool = False) -> None:
        self.events = events or []
        self.error = error
        self.calls: list[ChatRequest] = []

    def stream_chat(self, request: ChatRequest) -> Iterator[StreamEvent]:
        self.calls.append(request)
        if self.error:
            raise ProviderError("secret provider detail")
        yield from self.events


def test_summary_prompt_forbids_tools_and_requires_draft_then_final() -> None:
    assert "禁止调用任何工具" in SUMMARY_SYSTEM_PROMPT
    assert SUMMARY_SYSTEM_PROMPT.index("<analysis_draft>") < SUMMARY_SYSTEM_PROMPT.index("<final_summary>")
    assert all(SUMMARY_SYSTEM_PROMPT.count(heading) == 1 for heading in SUMMARY_HEADINGS)


def test_summary_request_has_no_tools_and_discards_draft() -> None:
    provider = ScriptedProvider(
        [
            StreamEvent(type="text_delta", text=valid_response()),
            StreamEvent(type="message_done"),
        ]
    )
    output = SummaryService(provider).summarize([Message(role="user", content="目标")], "旧摘要")

    assert output.summary.startswith(SUMMARY_HEADINGS[0])
    assert "临时分析" not in output.summary
    assert not hasattr(output, "draft")
    request = provider.calls[0]
    assert request.tools == ()
    assert request.cache_static_content is False
    assert "旧摘要" in request.messages[0].content


def test_summary_rejects_tool_calls_without_executing_them() -> None:
    provider = ScriptedProvider(
        [
            StreamEvent(type="tool_call_delta", tool_call_id="1", tool_name="read_file"),
            StreamEvent(type="text_delta", text=valid_response()),
            StreamEvent(type="message_done"),
        ]
    )

    with pytest.raises(SummaryFailure, match="尝试调用工具") as caught:
        SummaryService(provider).summarize([])

    assert caught.value.stage == "tool_call"


@pytest.mark.parametrize(
    ("text", "stage"),
    [
        ("", "empty"),
        ("<final_summary>x</final_summary>", "format"),
        ("<analysis_draft>x</analysis_draft><final_summary></final_summary>", "empty"),
        (
            "<analysis_draft>x</analysis_draft><final_summary>## 用户目标与原始要求\nx</final_summary>",
            "headings",
        ),
        (valid_response() + "<final_summary>duplicate</final_summary>", "format"),
    ],
)
def test_parse_summary_rejects_invalid_protocol(text: str, stage: str) -> None:
    with pytest.raises(SummaryFailure) as caught:
        parse_summary_response(text)

    assert caught.value.stage == stage


def test_summary_provider_failure_is_safe() -> None:
    provider = ScriptedProvider(error=True)

    with pytest.raises(SummaryFailure) as caught:
        SummaryService(provider).summarize([Message(role="user", content="secret body")])

    assert caught.value.stage == "api"
    assert "secret" not in caught.value.reason
