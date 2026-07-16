from __future__ import annotations

from typing import Literal


ToolSafety = Literal["read", "side_effect"]

READ_TOOLS = frozenset({"read_file", "find_files", "search_code"})


def is_read_tool(name: str) -> bool:
    return name in READ_TOOLS


def classify_tool(name: str) -> ToolSafety:
    return "read" if is_read_tool(name) else "side_effect"
