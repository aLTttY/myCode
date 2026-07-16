from __future__ import annotations

import re
import sys
from collections.abc import Callable
from typing import Protocol

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

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

_MENU_OPTIONS: tuple[tuple[str, ApprovalChoice], ...] = (
    ("不同意", "deny"),
    ("仅本次同意", "allow_once"),
    ("本会话同意", "allow_session"),
)

_CHOICE_LABELS = {choice: label for label, choice in _MENU_OPTIONS}


def safe_target_summary(target: str, max_chars: int = 300) -> str:
    redacted = _SECRET_PATTERN.sub(r"\1=<redacted>", target)
    if len(redacted) <= max_chars:
        return redacted
    return redacted[: max_chars - 3] + "..."


def select_approval_choice(
    *,
    input: Input | None = None,
    output: Output | None = None,
    require_tty: bool = True,
) -> ApprovalChoice:
    if require_tty and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        return "deny"

    selected = 0

    def menu_text() -> StyleAndTextTuples:
        fragments: StyleAndTextTuples = []
        for index, (label, _) in enumerate(_MENU_OPTIONS):
            if index == selected:
                fragments.append(("class:selected", f"> {label}\n"))
            else:
                fragments.append(("class:normal", f"  {label}\n"))
        return fragments

    control = FormattedTextControl(menu_text, focusable=True)
    bindings = KeyBindings()

    @bindings.add("up")
    def move_up(event) -> None:
        nonlocal selected
        selected = (selected - 1) % len(_MENU_OPTIONS)
        event.app.invalidate()

    @bindings.add("down")
    def move_down(event) -> None:
        nonlocal selected
        selected = (selected + 1) % len(_MENU_OPTIONS)
        event.app.invalidate()

    @bindings.add("enter")
    def confirm(event) -> None:
        event.app.exit(result=_MENU_OPTIONS[selected][1])

    @bindings.add("c-c")
    @bindings.add("c-d")
    def cancel(event) -> None:
        event.app.exit(result="deny")

    application: Application[ApprovalChoice] = Application(
        layout=Layout(Window(control)),
        key_bindings=bindings,
        style=Style.from_dict({"selected": "bold ansicyan", "normal": ""}),
        full_screen=False,
        erase_when_done=True,
        input=input,
        output=output,
    )
    try:
        return application.run()
    except (EOFError, KeyboardInterrupt, OSError):
        return "deny"
    except Exception:  # noqa: BLE001 - 交互审批异常必须安全拒绝。
        return "deny"


class TerminalApprovalHandler:
    def __init__(
        self,
        selector: Callable[[], ApprovalChoice] = select_approval_choice,
        output_func: Callable[[str], None] = print,
    ) -> None:
        self.selector = selector
        self.output_func = output_func

    def request(self, approval: ApprovalPrompt) -> ApprovalChoice:
        self.output_func(f"\n[permission] 工具：{approval.tool}")
        self.output_func(f"[permission] 目标：{safe_target_summary(approval.target)}")
        self.output_func(f"[permission] 原因：{approval.reason}")
        try:
            choice = self.selector()
        except (EOFError, KeyboardInterrupt, OSError):
            choice = "deny"
        except Exception:  # noqa: BLE001 - 交互审批异常必须安全拒绝。
            choice = "deny"
        self.output_func(f"[permission] 已选择：{_CHOICE_LABELS.get(choice, '不同意')}")
        return choice if choice in _CHOICE_LABELS else "deny"
