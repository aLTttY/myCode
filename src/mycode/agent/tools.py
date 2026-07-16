from __future__ import annotations

from dataclasses import dataclass

from mycode.tools.registry import ToolRegistry
from mycode.tools.safety import READ_TOOLS, ToolSafety, classify_tool
from mycode.types import ToolCall


@dataclass(frozen=True)
class ToolBatch:
    safety: ToolSafety
    calls: tuple[ToolCall, ...]


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
