import threading
import time

import pytest

from mycode.agents.models import ChildRunSpec, TaskOutcome
from mycode.agents.tasks import AgentTaskCapacityError, AgentTaskManager


def spec(task_id: str, *, session: str = "s", background: bool = True) -> ChildRunSpec:
    return ChildRunSpec(
        task_id, session, "fork", "work", None, "model", background,
        "default", None,
    )


def test_fifo_capacity_and_unique_notification() -> None:
    gate = threading.Event()
    started: list[str] = []
    notifications = []

    def execute(run_spec, cancellation):
        started.append(run_spec.task_id)
        gate.wait(1)
        return TaskOutcome("completed", result=run_spec.task_id)

    manager = AgentTaskManager(
        execute, max_concurrency=1, max_queue_size=2,
        notification_sink=notifications.append,
    )
    manager.submit(spec("one"))
    manager.submit(spec("two"))
    manager.submit(spec("three"))
    with pytest.raises(AgentTaskCapacityError):
        manager.submit(spec("four"))
    gate.set()
    manager.wait_task("s", "three", 2)

    assert started == ["one", "two", "three"]
    assert [item.task_id for item in notifications] == ["one", "two", "three"]
    assert [item.task_id for item in manager.take_inbox("s")] == ["one", "two", "three"]
    assert manager.take_inbox("s") == ()
    assert manager.shutdown(1).unfinished == 0


def test_foreground_timeout_changes_delivery_without_restart() -> None:
    gate = threading.Event()
    starts = 0

    def execute(run_spec, cancellation):
        nonlocal starts
        starts += 1
        gate.wait(1)
        return TaskOutcome("completed", result="done")

    manager = AgentTaskManager(execute, max_concurrency=1)
    manager.submit(spec("one", background=False))
    result = manager.finish_foreground_wait("s", "one", "timeout")
    gate.set()
    details = manager.wait_task("s", "one", 2)

    assert result.completed is False
    assert result.details.snapshot.delivery_mode == "background"
    assert details.result == "done"
    assert starts == 1
    assert manager.shutdown(1).unfinished == 0


def test_session_ownership_cancel_and_clear_inbox() -> None:
    gate = threading.Event()

    def execute(run_spec, cancellation):
        while not cancellation.is_cancelled() and not gate.wait(0.01):
            pass
        return TaskOutcome("cancelled", failure_reason="cancelled")

    manager = AgentTaskManager(execute, max_concurrency=1)
    manager.submit(spec("one", session="old"))
    time.sleep(0.02)

    with pytest.raises(Exception, match="不属于当前会话"):
        manager.get_task("new", "one")
    assert manager.cancel_session("old", clear_inbox=True) == 1
    assert manager.get_task("old", "one").snapshot.status in {"cancelling", "cancelled"}
    assert manager.wait_session("old", 1.0) == 0
    assert manager.get_task("old", "one").snapshot.status == "cancelled"
    assert manager.take_inbox("old") == ()
    gate.set()
    manager.shutdown(1)


def test_wait_session_tracks_cancelled_work_until_executor_actually_returns() -> None:
    started = threading.Event()
    release = threading.Event()

    def execute(run_spec, cancellation):
        started.set()
        release.wait(1)
        return TaskOutcome("cancelled", failure_reason="cancelled")

    manager = AgentTaskManager(execute, max_concurrency=1)
    manager.submit(spec("one", session="old"))
    assert started.wait(1)
    manager.cancel_session("old", clear_inbox=True)

    assert manager.wait_session("old", 0.001) == 1
    release.set()
    assert manager.wait_session("old", 1) == 0
    manager.shutdown(1)
