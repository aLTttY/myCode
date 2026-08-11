from __future__ import annotations

import re
from collections.abc import Iterable

from mycode.tools.base import Tool
from mycode.tools.command import RunCommandTool
from mycode.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from mycode.tools.git import ReadGitChangesTool
from mycode.tools.search import FindFilesTool, SearchCodeTool
from mycode.types import ToolError, ToolSpec


TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_valid_tool_name(name: str) -> bool:
    return TOOL_NAME_PATTERN.fullmatch(name) is not None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if not is_valid_tool_name(name):
            raise ToolError(
                f"工具名 `{name}` 非法；只能使用字母、数字、下划线、连字符，且长度为 1-64。"
            )
        if name in self._tools:
            raise ToolError(f"工具 `{name}` 已注册。")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"未知工具：{name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def subset(self, names: Iterable[str]) -> ToolRegistry:
        registry = ToolRegistry()
        for name in names:
            registry.register(self.get(name))
        return registry

    def copy(self) -> ToolRegistry:
        return self.subset(self.names())

    def merge(self, *others: ToolRegistry) -> ToolRegistry:
        registry = self.copy()
        for other in others:
            for name in other.names():
                registry.register(other.get(name))
        return registry

    def tool_specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def as_openai_tools(self) -> list[dict[str, object]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self.tool_specs()
        ]


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    registry.register(RunCommandTool())
    registry.register(FindFilesTool())
    registry.register(SearchCodeTool())
    registry.register(ReadGitChangesTool())
    return registry
