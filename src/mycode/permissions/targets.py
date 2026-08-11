from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from threading import RLock

from mycode.types import ToolCall

from .models import PermissionRequest, PermissionValidationError
from .sandbox import resolve_workspace_path, validate_pattern_target


FILE_TOOLS = {"read_file", "write_file", "edit_file"}


def _required_string(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise PermissionValidationError("invalid_target", f"参数 `{key}` 必须是非空字符串。")
    return value


class PermissionTargetResolver:
    def __init__(
        self,
        mcp_tool_prefixes: tuple[str, ...] = (),
        dynamic_call_tools: tuple[str, ...] = (),
    ) -> None:
        self.mcp_tool_prefixes = tuple(mcp_tool_prefixes)
        self._dynamic_call_tools = frozenset(dynamic_call_tools)
        self._lock = RLock()

    def update_dynamic_call_tools(self, names: set[str] | frozenset[str]) -> None:
        with self._lock:
            self._dynamic_call_tools = frozenset(names)

    def resolve(self, call: ToolCall, workspace_root: Path) -> PermissionRequest:
        if call.name in FILE_TOOLS:
            _, target = resolve_workspace_path(workspace_root, _required_string(call.arguments, "path"))
        elif call.name == "run_command":
            target = _required_string(call.arguments, "command")
        elif call.name == "find_files":
            target = validate_pattern_target(_required_string(call.arguments, "pattern"))
        elif call.name == "search_code":
            path = call.arguments.get("path", ".")
            if not isinstance(path, str) or not path:
                raise PermissionValidationError("invalid_target", "参数 `path` 必须是非空字符串。")
            _, target = resolve_workspace_path(workspace_root, path)
        elif any(
            call.name.startswith(prefix) and len(call.name) > len(prefix)
            for prefix in self.mcp_tool_prefixes
        ):
            target = "call"
        elif self._is_dynamic_call_tool(call.name):
            target = "call"
        else:
            raise PermissionValidationError("unknown_tool", f"未知工具：{call.name}")
        return PermissionRequest(
            tool_call_id=call.id,
            tool=call.name,
            target=target,
            arguments=call.arguments,
            workspace_root=workspace_root.resolve(),
        )

    def _is_dynamic_call_tool(self, name: str) -> bool:
        with self._lock:
            return name in self._dynamic_call_tools
