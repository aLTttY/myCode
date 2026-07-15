from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from prompt_toolkit import prompt

from .models import ApprovalChoice, ApprovalPrompt


class ApprovalHandler(Protocol):
    def request(self, approval: ApprovalPrompt) -> ApprovalChoice:
        ...


class DenyApprovalHandler:
    def request(self, approval: ApprovalPrompt) -> ApprovalChoice:
        return "deny"


_SECRET_PATTERN = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:token|secret|password|api_?key)[A-Za-z0-9_]*)=([^\s]+)"
)


def safe_target_summary(target: str, max_chars: int = 300) -> str:
    redacted = _SECRET_PATTERN.sub(r"\1=<redacted>", target)
    if len(redacted) <= max_chars:
        return redacted
    return redacted[: max_chars - 3] + "..."


class TerminalApprovalHandler:
    def __init__(
        self,
        input_func: Callable[[str], str] = prompt,
        output_func: Callable[[str], None] = print,
    ) -> None:
        self.input_func = input_func
        self.output_func = output_func

    def request(self, approval: ApprovalPrompt) -> ApprovalChoice:
        self.output_func(f"\n[permission] 工具：{approval.tool}")
        self.output_func(f"[permission] 目标：{safe_target_summary(approval.target)}")
        self.output_func(f"[permission] 原因：{approval.reason}")
        choices: dict[str, ApprovalChoice] = {
            "d": "deny",
            "deny": "deny",
            "o": "allow_once",
            "once": "allow_once",
            "s": "allow_session",
            "session": "allow_session",
            "p": "allow_permanent",
            "permanent": "allow_permanent",
        }
        while True:
            try:
                value = self.input_func("[permission] [d]拒绝 [o]本次 [s]本会话 [p]永久：").strip().lower()
            except EOFError:
                return "deny"
            choice = choices.get(value)
            if choice is not None:
                return choice
            self.output_func("[permission] 无效选择，请重新输入。")
