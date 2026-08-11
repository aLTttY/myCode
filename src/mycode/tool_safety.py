from __future__ import annotations

from typing import Literal


ToolSafety = Literal["read", "side_effect"]

READ_TOOLS = frozenset(
    {"read_file", "find_files", "search_code", "read_git_changes"}
)
SYSTEM_TOOLS = frozenset({"load_skill"})


def is_read_tool(name: str) -> bool:
    return name in READ_TOOLS


def is_system_tool(name: str) -> bool:
    return name in SYSTEM_TOOLS


def classify_tool(name: str) -> ToolSafety:
    return "read" if is_read_tool(name) else "side_effect"
