from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PromptMode = Literal["default", "plan", "do"]


RUNTIME_INSTRUCTION_TAG = "mewcode_runtime_instruction"


@dataclass(frozen=True)
class DynamicInstruction:
    tag: str
    content: str
    full: bool

    def render(self) -> str:
        return f"<{self.tag}>\n{self.content}\n</{self.tag}>"


def mode_instruction(mode: PromptMode, iteration: int, repeat_interval: int) -> DynamicInstruction:
    full = iteration == 1 or (repeat_interval > 0 and iteration % repeat_interval == 0)
    content = _full_instruction(mode) if full else _compact_instruction(mode)
    return DynamicInstruction(tag=RUNTIME_INSTRUCTION_TAG, content=content, full=full)


def _full_instruction(mode: PromptMode) -> str:
    if mode == "plan":
        return (
            "当前为 Plan Mode。只允许观察、分析和产出计划。只能使用只读工具，"
            "不得写文件、改文件或执行命令。输出可执行计划，不要执行计划。"
        )
    if mode == "do":
        return (
            "当前为 Do Mode。可以在全局规则、安全边界和工具约定下使用完整工具集推进实际工作。"
            "编辑前先读取或搜索确认当前内容，优先使用专用工具。"
        )
    return (
        "当前为 default 模式。可以在全局规则、安全边界和工具约定下使用完整工具集完成用户任务。"
        "编辑前先读取或搜索确认当前内容，优先使用专用工具。"
    )


def _compact_instruction(mode: PromptMode) -> str:
    if mode == "plan":
        return "Plan Mode 提醒：只读观察并输出计划，不写文件、不改文件、不执行命令。"
    if mode == "do":
        return "Do Mode 提醒：可使用完整工具集；编辑前先读取或搜索确认，优先使用专用工具。"
    return "default 模式提醒：可使用完整工具集；编辑前先读取或搜索确认，优先使用专用工具。"
