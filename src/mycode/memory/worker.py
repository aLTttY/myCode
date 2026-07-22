from __future__ import annotations

import queue
import secrets
import threading
import time

from .models import MemoryJob, MemoryNotice, TurnSnapshot
from .service import MemoryService


class MemoryWorker:
    def __init__(self, service: MemoryService) -> None:
        self.service = service
        self._queue: queue.Queue[MemoryJob] = queue.Queue()
        self._notices: queue.Queue[MemoryNotice] = queue.Queue()
        self._condition = threading.Condition()
        self._jobs: dict[str, MemoryJob] = {}
        self._thread = threading.Thread(target=self._run, name="mycode-memory", daemon=True)
        self._thread.start()

    def submit(self, snapshot: TurnSnapshot) -> str:
        job = MemoryJob(secrets.token_hex(8), snapshot)
        with self._condition:
            self._jobs[job.job_id] = job
        self._queue.put(job)
        return job.job_id

    def drain(self, timeout: float = 5.0) -> tuple[MemoryNotice, ...]:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._jobs:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    for job in self._jobs.values():
                        job.cancelled.set()
                    self._notices.put(MemoryNotice("timeout", "自动记忆等待超时，未提交任务已取消。"))
                    break
                self._condition.wait(remaining)
        return self.take_notices()

    def take_notices(self) -> tuple[MemoryNotice, ...]:
        notices: list[MemoryNotice] = []
        while True:
            try:
                notices.append(self._notices.get_nowait())
            except queue.Empty:
                return tuple(notices)

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                for notice in self.service.process(job.snapshot, job.cancelled):
                    self._notices.put(notice)
            except Exception as exc:  # Worker must isolate a failed memory job.
                self._notices.put(MemoryNotice("worker_failed", f"自动记忆任务失败（{type(exc).__name__}）。"))
            finally:
                with self._condition:
                    self._jobs.pop(job.job_id, None)
                    self._condition.notify_all()
                self._queue.task_done()
