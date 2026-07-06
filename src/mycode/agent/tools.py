from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mycode.tools.registry import ToolRegistry
from mycode.types import ToolCall


ToolSafety = Literal["read", "side_effect"]

READ_TOOLS = {"read_file", "find_files", "search_code"}
SIDE_EFFECT_TOOLS = {"write_file", "edit_file", "run_command"}


@dataclass(frozen=True)
class ToolBatch:
    safety: ToolSafety
    calls: tuple[ToolCall, ...]


def classify_tool(name: str) -> ToolSafety:
    if name in READ_TOOLS:
        return "read"
    return "side_effect"


def create_readonly_registry(full_registry: ToolRegistry) -> ToolRegistry:
    registry = ToolRegistry()
    for name in sorted(READ_TOOLS):
        registry.register(full_registry.get(name))
    return registry


class ToolBatcher:
    def batch(self, calls: tuple[ToolCall, ...] | list[ToolCall]) -> list[ToolBatch]:
        batches: list[ToolBatch] = []
        current_safety: ToolSafety | None = None
        current_calls: list[ToolCall] = []

        for call in calls:
            safety = classify_tool(call.name)
            if current_safety is None:
                current_safety = safety
            if safety != current_safety:
                batches.append(ToolBatch(safety=current_safety, calls=tuple(current_calls)))
                current_safety = safety
                current_calls = []
            current_calls.append(call)

        if current_safety is not None:
            batches.append(ToolBatch(safety=current_safety, calls=tuple(current_calls)))
        return batches
