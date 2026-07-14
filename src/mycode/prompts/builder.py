from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mycode.prompts.modes import DynamicInstruction, mode_instruction
from mycode.prompts.modules import PromptOptions, fixed_prompt_modules, optional_prompt_modules, render_modules


ENVIRONMENT_TAG = "mewcode_environment"
PromptMode = Literal["default", "plan", "do"]


@dataclass(frozen=True)
class EnvironmentInfo:
    cwd: str
    date: str
    mode: PromptMode


@dataclass(frozen=True)
class PromptBundle:
    stable_system_prompt: str
    optional_system_prompt: str
    dynamic_system_messages: tuple[DynamicInstruction, ...]
    environment_message: DynamicInstruction


class PromptBuilder:
    def __init__(self, repeat_interval: int = 3) -> None:
        self.repeat_interval = repeat_interval

    def build(
        self,
        mode: PromptMode,
        iteration: int,
        environment: EnvironmentInfo,
        options: PromptOptions = PromptOptions(),
    ) -> PromptBundle:
        stable_system_prompt = render_modules(fixed_prompt_modules())
        optional_system_prompt = render_modules(optional_prompt_modules(options))
        environment_message = DynamicInstruction(
            tag=ENVIRONMENT_TAG,
            content=f"cwd: {environment.cwd}\ndate: {environment.date}\nmode: {environment.mode}",
            full=True,
        )
        dynamic_messages = (mode_instruction(mode, iteration, self.repeat_interval),)
        return PromptBundle(
            stable_system_prompt=stable_system_prompt,
            optional_system_prompt=optional_system_prompt,
            dynamic_system_messages=dynamic_messages,
            environment_message=environment_message,
        )
