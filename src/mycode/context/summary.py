from __future__ import annotations

import json
import re
from dataclasses import asdict
from dataclasses import dataclass
from typing import Sequence

from mycode.providers.base import ChatRequest, LLMProvider
from mycode.types import Message, ProviderError

from .models import SummaryOutput
from .prompts import SUMMARY_HEADINGS, SUMMARY_SYSTEM_PROMPT


@dataclass(frozen=True)
class SummaryFailure(Exception):
    stage: str
    reason: str

    def __str__(self) -> str:
        return self.reason


class SummaryService:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider

    def summarize(
        self,
        messages: Sequence[Message],
        previous_summary: str = "",
    ) -> SummaryOutput:
        request = self._request(messages, previous_summary)
        parts: list[str] = []
        saw_tool_call = False
        try:
            for event in self.provider.stream_chat(request):
                if event.type == "text_delta":
                    parts.append(event.text)
                elif event.type in {"tool_call_delta", "tool_call_done"}:
                    saw_tool_call = True
                elif event.type == "message_done":
                    break
        except ProviderError as exc:
            raise SummaryFailure("api", "摘要 API 调用失败。") from exc

        if saw_tool_call:
            raise SummaryFailure("tool_call", "摘要模型违反约束并尝试调用工具。")
        return parse_summary_response("".join(parts))

    def _request(
        self,
        messages: Sequence[Message],
        previous_summary: str,
    ) -> ChatRequest:
        payload = {
            "previous_summary": previous_summary,
            "messages": [asdict(message) for message in messages],
        }
        return ChatRequest(
            stable_system_prompt=SUMMARY_SYSTEM_PROMPT,
            dynamic_system_messages=(),
            messages=(
                Message(
                    role="user",
                    content=json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            ),
            tools=(),
            cache_static_content=False,
        )


def parse_summary_response(text: str) -> SummaryOutput:
    if not text.strip():
        raise SummaryFailure("empty", "摘要模型返回了空响应。")
    tags = (
        "<analysis_draft>",
        "</analysis_draft>",
        "<final_summary>",
        "</final_summary>",
    )
    if any(text.count(tag) != 1 for tag in tags):
        raise SummaryFailure("format", "摘要响应缺少唯一的草稿或正式摘要标记。")
    positions = tuple(text.index(tag) for tag in tags)
    if positions != tuple(sorted(positions)):
        raise SummaryFailure("format", "摘要响应标记顺序无效。")

    final_start = positions[2] + len(tags[2])
    final_end = positions[3]
    summary = text[final_start:final_end].strip()
    if not summary:
        raise SummaryFailure("empty", "正式摘要为空。")

    actual_headings = tuple(
        line.strip()
        for line in summary.splitlines()
        if re.match(r"^##\s+", line.strip())
    )
    if actual_headings != SUMMARY_HEADINGS:
        raise SummaryFailure("headings", "正式摘要没有严格包含六个固定部分。")
    return SummaryOutput(summary=summary, headings=actual_headings)
