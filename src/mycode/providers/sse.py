from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from mycode.types import ProviderError


def iter_sse_data_lines(response: Any) -> Iterator[str]:
    try:
        for raw_line in response.iter_lines():
            line = _normalize_line(raw_line)
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            yield line.removeprefix("data:").strip()
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - Provider 边界需要包装底层流异常。
        raise ProviderError("读取流式响应时发生错误。") from exc


def _normalize_line(raw_line: str | bytes) -> str:
    if isinstance(raw_line, bytes):
        return raw_line.decode("utf-8", errors="replace").strip()
    return raw_line.strip()
