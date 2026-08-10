import threading
import time
from pathlib import Path

from mycode.memory import MemoryService, MemoryStore, MemoryWorker, TurnSnapshot
from mycode.memory.models import MemoryNotice


class Service:
    def __init__(self) -> None:
        self.order = []

    def process(self, snapshot, cancelled):
        self.order.append(snapshot.user_text)
        return (MemoryNotice("updated", "done"),)


def test_worker_runs_fifo_and_drains() -> None:
    service = Service()
    worker = MemoryWorker(service)  # type: ignore[arg-type]
    worker.submit(TurnSnapshot("s", "1", "a"))
    worker.submit(TurnSnapshot("s", "2", "a"))

    notices = worker.drain(1)

    assert service.order == ["1", "2"]
    assert [notice.code for notice in notices] == ["updated", "updated"]
    assert worker.status().state == "idle"
    assert worker.status().pending_jobs == 0


def test_worker_drain_times_out_and_cancels_running_job() -> None:
    started = threading.Event()
    release = threading.Event()
    saw_cancelled: list[bool] = []

    class BlockingService:
        def process(self, snapshot, cancelled):
            started.set()
            release.wait(1)
            saw_cancelled.append(cancelled.is_set())
            return ()

    worker = MemoryWorker(BlockingService())  # type: ignore[arg-type]
    worker.submit(TurnSnapshot("s", "1", "a"))
    assert started.wait(1)
    before = time.monotonic()

    notices = worker.drain(0.02)
    elapsed = time.monotonic() - before
    release.set()
    time.sleep(0.03)

    assert elapsed < 0.2
    assert any(notice.code == "timeout" for notice in notices)
    assert saw_cancelled == [True]


def test_worker_status_is_nonblocking_and_counts_active_jobs() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingService:
        def process(self, snapshot, cancelled):
            started.set()
            release.wait(1)
            return ()

    worker = MemoryWorker(BlockingService())  # type: ignore[arg-type]
    assert worker.status().state == "idle"
    worker.submit(TurnSnapshot("s", "1", "a"))
    assert started.wait(1)

    before = time.monotonic()
    status = worker.status()
    elapsed = time.monotonic() - before

    assert elapsed < 0.1
    assert status.state == "busy"
    assert status.pending_jobs == 1
    release.set()
    worker.drain(1)
    assert worker.status().state == "idle"
    assert worker.status().pending_jobs == 0
