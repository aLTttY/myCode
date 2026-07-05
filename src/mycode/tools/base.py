from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from mycode.types import ToolContext, ToolError, ToolResult, ToolSpec


class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec:
        ...

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        ...


def require_str(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(f"参数 `{key}` 必须是非空字符串。")
    return value


def require_string(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str):
        raise ToolError(f"参数 `{key}` 必须是字符串。")
    return value


def optional_bool(arguments: Mapping[str, object], key: str, default: bool) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"参数 `{key}` 必须是布尔值。")
    return value


def optional_float(arguments: Mapping[str, object], key: str, default: float) -> float:
    value = arguments.get(key, default)
    if not isinstance(value, (int, float)):
        raise ToolError(f"参数 `{key}` 必须是数字。")
    return float(value)


def resolve_workspace_path(workspace_root: Path, value: str) -> Path:
    requested = Path(value)
    if requested.is_absolute():
        raise ToolError("路径必须是工作区内的相对路径。")

    root = workspace_root.resolve()
    resolved = (root / requested).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError("路径不能指向工作区外。") from exc
    return resolved


def truncate_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def result_error(message: str, **data: object) -> ToolResult:
    return ToolResult(ok=False, message=message, data=data)


def result_ok(message: str, **data: object) -> ToolResult:
    return ToolResult(ok=True, message=message, data=data)
