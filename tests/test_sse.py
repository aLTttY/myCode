from __future__ import annotations

import pytest

from mycode.providers.sse import iter_sse_data_lines
from mycode.types import ProviderError


class FakeResponse:
    def __init__(self, lines: list[str | bytes]) -> None:
        self._lines = lines

    def iter_lines(self):
        yield from self._lines


class BrokenResponse:
    def iter_lines(self):
        yield "data: first"
        raise RuntimeError("stream broke")


def test_iter_sse_data_lines_extracts_data() -> None:
    response = FakeResponse(["", ": ping", "data: {\"ok\": true}", b"data: [DONE]"])

    assert list(iter_sse_data_lines(response)) == ['{"ok": true}', "[DONE]"]


def test_iter_sse_data_lines_ignores_non_data_lines() -> None:
    response = FakeResponse(["event: message", "id: 1", "data: hello"])

    assert list(iter_sse_data_lines(response)) == ["hello"]


def test_iter_sse_data_lines_wraps_stream_errors() -> None:
    with pytest.raises(ProviderError, match="流式响应"):
        list(iter_sse_data_lines(BrokenResponse()))
