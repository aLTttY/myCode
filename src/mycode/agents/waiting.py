from __future__ import annotations

import threading
import sys
from typing import Literal, Protocol


WaitReason = Literal["completed", "timeout", "manual"]


class ForegroundWaiter(Protocol):
    def wait(
        self,
        task_id: str,
        done: threading.Event,
        timeout_seconds: float,
    ) -> WaitReason:
        ...


class EventForegroundWaiter:
    def wait(
        self,
        task_id: str,
        done: threading.Event,
        timeout_seconds: float,
    ) -> WaitReason:
        del task_id
        return "completed" if done.wait(timeout_seconds) else "timeout"


class PromptToolkitForegroundWaiter:
    """Wait for completion while allowing an interactive Ctrl+B detach."""

    def __init__(self, fallback: ForegroundWaiter | None = None) -> None:
        self.fallback = fallback or EventForegroundWaiter()

    def wait(
        self,
        task_id: str,
        done: threading.Event,
        timeout_seconds: float,
    ) -> WaitReason:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return self.fallback.wait(task_id, done, timeout_seconds)
        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.layout.containers import Window
        except Exception:
            return self.fallback.wait(task_id, done, timeout_seconds)

        state: dict[str, WaitReason] = {"reason": "timeout"}
        bindings = KeyBindings()

        @bindings.add("c-b")
        def _detach(event) -> None:
            state["reason"] = "manual"
            event.app.exit(result="manual")

        app = Application(
            layout=Layout(
                Window(
                    FormattedTextControl(
                        f"等待子 Agent {task_id}；按 Ctrl+B 转入后台…"
                    ),
                    height=1,
                )
            ),
            key_bindings=bindings,
            full_screen=False,
        )

        def watch() -> None:
            state["reason"] = "completed" if done.wait(timeout_seconds) else "timeout"
            try:
                app.exit(result=state["reason"])
            except Exception:
                pass

        threading.Thread(target=watch, name="agent-foreground-wait", daemon=True).start()
        try:
            result = app.run()
        except Exception:
            return self.fallback.wait(task_id, done, 0.001)
        return result if result in {"completed", "timeout", "manual"} else state["reason"]
