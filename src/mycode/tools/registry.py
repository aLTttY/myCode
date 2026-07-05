from __future__ import annotations

from mycode.tools.base import Tool
from mycode.tools.command import RunCommandTool
from mycode.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from mycode.tools.search import FindFilesTool, SearchCodeTool
from mycode.types import ToolError, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ToolError(f"工具 `{name}` 已注册。")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"未知工具：{name}") from exc

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
    return registry
