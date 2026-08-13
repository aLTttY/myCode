import threading

from mycode.agents.waiting import EventForegroundWaiter, PromptToolkitForegroundWaiter


def test_event_waiter_reports_completed_and_timeout() -> None:
    done = threading.Event()
    done.set()

    assert EventForegroundWaiter().wait("task", done, 1) == "completed"
    assert EventForegroundWaiter().wait("task", threading.Event(), 0.001) == "timeout"


def test_prompt_waiter_uses_event_fallback_without_tty(monkeypatch) -> None:
    class NonTTY:
        def isatty(self):
            return False

    monkeypatch.setattr("mycode.agents.waiting.sys.stdin", NonTTY())
    done = threading.Event()
    done.set()

    assert PromptToolkitForegroundWaiter().wait("task", done, 1) == "completed"
