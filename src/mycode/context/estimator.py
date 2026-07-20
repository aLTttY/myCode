from __future__ import annotations

import json
import math
from dataclasses import asdict

from mycode.providers.base import ChatRequest
from mycode.types import TokenUsage

from .models import TokenAnchor


def approximate_tokens(text: str) -> int:
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return non_ascii_chars + math.ceil(ascii_chars / 3)


def request_snapshot(request: ChatRequest) -> str:
    payload = {
        "stable_system_prompt": request.stable_system_prompt,
        "dynamic_system_messages": [message.render() for message in request.dynamic_system_messages],
        "optional_system_prompt": request.optional_system_prompt,
        "messages": [asdict(message) for message in request.messages],
        "tools": [asdict(tool) for tool in request.tools],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class TokenEstimator:
    def __init__(self, anchor: TokenAnchor | None = None) -> None:
        self._anchor = anchor

    @property
    def anchor(self) -> TokenAnchor | None:
        return self._anchor

    def snapshot_score(self, request: ChatRequest) -> int:
        return approximate_tokens(request_snapshot(request))

    def estimate(self, request: ChatRequest) -> int:
        score = self.snapshot_score(request)
        if self._anchor is None:
            return score
        return max(0, self._anchor.input_tokens + score - self._anchor.snapshot_score)

    def record_usage(self, request: ChatRequest, usage: TokenUsage | None) -> bool:
        if usage is None or usage.input_tokens is None:
            return False
        self._anchor = TokenAnchor(
            input_tokens=usage.input_tokens,
            snapshot_score=self.snapshot_score(request),
        )
        return True
