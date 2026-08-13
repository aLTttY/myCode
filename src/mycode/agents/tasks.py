from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone

from mycode.types import UserFacingError

from .models import (
    ChildRunSpec,
    ForegroundWaitResult,
    InboxItem,
    ShutdownReport,
    TaskDetails,
    TaskOutcome,
    TaskRecord,
    TaskSnapshot,
)


TaskExecutor = Callable[[ChildRunSpec, object], TaskOutcome]
NotificationSink = Callable[[InboxItem], None]


class AgentTaskCapacityError(UserFacingError):
    pass


class AgentTaskAccessError(UserFacingError):
    pass


class AgentTaskManager:
    def __init__(
        self,
        executor: TaskExecutor,
        *,
        max_concurrency: int = 4,
        max_queue_size: int = 32,
        inbox_preview_chars: int = 8_000,
        notification_sink: NotificationSink | None = None,
    ) -> None:
        if not 1 <= max_concurrency <= 32:
            raise ValueError("max_concurrency 必须在 1–32 之间。")
        if not 0 <= max_queue_size <= 1024:
            raise ValueError("max_queue_size 必须在 0–1024 之间。")
        self._executor = executor
        self._max_concurrency = max_concurrency
        self._max_queue_size = max_queue_size
        self._preview_chars = inbox_preview_chars
        self._notification_sink = notification_sink
        self._records: dict[str, TaskRecord] = {}
        self._queue: deque[str] = deque()
        self._inbox: dict[str, list[InboxItem]] = defaultdict(list)
        self._running = 0
        self._active_task_ids: set[str] = set()
        self._closed = False
        self._condition = threading.Condition(threading.RLock())
        self._workers = tuple(
            threading.Thread(
                target=self._worker,
                name=f"mycode-agent-{index + 1}",
                daemon=True,
            )
            for index in range(max_concurrency)
        )
        for worker in self._workers:
            worker.start()

    def submit(self, spec: ChildRunSpec) -> TaskSnapshot:
        from mycode.agent.cancellation import CancellationToken

        with self._condition:
            if self._closed:
                raise AgentTaskCapacityError("后台任务管理器已关闭。")
            if spec.task_id in self._records:
                raise AgentTaskCapacityError(f"任务 ID 已存在：{spec.task_id}")
            if self._running + len(self._queue) >= self._max_concurrency + self._max_queue_size:
                raise AgentTaskCapacityError("子 Agent 队列已满，请稍后重试。")
            now = datetime.now(timezone.utc)
            delivery = "background" if spec.initial_background else "foreground"
            record = TaskRecord(
                spec=spec,
                status="queued",
                delivery_mode=delivery,
                created_at=now,
                started_at=None,
                finished_at=None,
                cancel_requested=False,
                outcome=None,
                cancellation=CancellationToken(),
                done=threading.Event(),
            )
            self._records[spec.task_id] = record
            self._queue.append(spec.task_id)
            snapshot = self._snapshot(record)
            self._condition.notify()
            return snapshot

    def done_event(self, session_id: str, task_id: str) -> threading.Event:
        with self._condition:
            return self._owned(session_id, task_id).done

    def is_background(self, task_id: str) -> bool:
        with self._condition:
            record = self._records.get(task_id)
            return record is not None and record.delivery_mode == "background"

    def finish_foreground_wait(
        self,
        session_id: str,
        task_id: str,
        reason: str,
    ) -> ForegroundWaitResult:
        if reason not in {"completed", "timeout", "manual"}:
            raise ValueError("未知前台等待结束原因。")
        with self._condition:
            record = self._owned(session_id, task_id)
            if record.status in {"completed", "failed", "cancelled"}:
                return ForegroundWaitResult(True, self._details(record))
            record.delivery_mode = "background"
            return ForegroundWaitResult(False, self._details(record))

    def list_tasks(self, session_id: str) -> tuple[TaskSnapshot, ...]:
        with self._condition:
            return tuple(
                self._snapshot(record)
                for record in self._records.values()
                if record.spec.session_id == session_id
            )

    def get_task(self, session_id: str, task_id: str) -> TaskDetails:
        with self._condition:
            return self._details(self._owned(session_id, task_id))

    def wait_task(
        self,
        session_id: str,
        task_id: str,
        timeout_seconds: float,
    ) -> TaskDetails:
        event = self.done_event(session_id, task_id)
        event.wait(timeout_seconds)
        return self.get_task(session_id, task_id)

    def cancel_task(self, session_id: str, task_id: str) -> TaskSnapshot:
        notification: InboxItem | None = None
        with self._condition:
            record = self._owned(session_id, task_id)
            if record.status in {"completed", "failed", "cancelled"}:
                return self._snapshot(record)
            record.cancel_requested = True
            record.cancellation.cancel()
            if record.status == "queued":
                try:
                    self._queue.remove(task_id)
                except ValueError:
                    pass
            record.status = "cancelled"
            record.finished_at = datetime.now(timezone.utc)
            record.outcome = TaskOutcome("cancelled", failure_reason="任务已取消。")
            record.done.set()
            notification = self._deliver_locked(record)
            self._condition.notify_all()
            snapshot = self._snapshot(record)
        self._notify(notification)
        return snapshot

    def take_inbox(self, session_id: str) -> tuple[InboxItem, ...]:
        with self._condition:
            items = tuple(self._inbox.pop(session_id, ()))
            return items

    def restore_inbox(self, session_id: str, items: tuple[InboxItem, ...]) -> None:
        if not items:
            return
        with self._condition:
            self._inbox[session_id][0:0] = list(items)

    def cancel_session(self, session_id: str, *, clear_inbox: bool) -> int:
        with self._condition:
            ids = [
                record.spec.task_id
                for record in self._records.values()
                if record.spec.session_id == session_id
                and record.status not in {"completed", "failed", "cancelled"}
            ]
        for task_id in ids:
            self.cancel_task(session_id, task_id)
        if clear_inbox:
            with self._condition:
                self._inbox.pop(session_id, None)
        return len(ids)

    def wait_session(self, session_id: str, timeout_seconds: float) -> int:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while True:
                unfinished = [
                    record
                    for record in self._records.values()
                    if record.spec.session_id == session_id
                    and record.status not in {"completed", "failed", "cancelled"}
                ]
                active = [
                    task_id
                    for task_id in self._active_task_ids
                    if self._records[task_id].spec.session_id == session_id
                ]
                if not unfinished and not active:
                    return 0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return len(set(active) | {item.spec.task_id for item in unfinished})
                self._condition.wait(remaining)

    def shutdown(self, timeout_seconds: float) -> ShutdownReport:
        with self._condition:
            if self._closed:
                unfinished = sum(worker.is_alive() for worker in self._workers)
                return ShutdownReport(0, unfinished)
            self._closed = True
            targets = [
                (record.spec.session_id, record.spec.task_id)
                for record in self._records.values()
                if record.status not in {"completed", "failed", "cancelled"}
            ]
        for session_id, task_id in targets:
            self.cancel_task(session_id, task_id)
        with self._condition:
            self._condition.notify_all()
        deadline = time.monotonic() + timeout_seconds
        for worker in self._workers:
            worker.join(max(0.0, deadline - time.monotonic()))
        return ShutdownReport(len(targets), sum(worker.is_alive() for worker in self._workers))

    def _worker(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or bool(self._queue))
                if self._closed and not self._queue:
                    return
                task_id = self._queue.popleft()
                record = self._records[task_id]
                if record.status != "queued":
                    continue
                record.status = "running"
                record.started_at = datetime.now(timezone.utc)
                self._running += 1
                self._active_task_ids.add(task_id)
                spec = record.spec
                cancellation = record.cancellation
            try:
                outcome = self._executor(spec, cancellation)
                if outcome.status not in {"completed", "failed", "cancelled"}:
                    raise ValueError("子 Agent 返回了非法终态。")
            except Exception as exc:
                outcome = TaskOutcome(
                    "failed",
                    failure_reason=f"子 Agent 执行失败（{type(exc).__name__}）。",
                )
            notification: InboxItem | None = None
            with self._condition:
                self._running -= 1
                self._active_task_ids.discard(task_id)
                record = self._records[task_id]
                if record.status not in {"completed", "failed", "cancelled"}:
                    if record.cancel_requested:
                        outcome = TaskOutcome(
                            "cancelled",
                            failure_reason="任务已取消。",
                            token_usage=outcome.token_usage,
                            permission_audit=outcome.permission_audit,
                        )
                    record.status = outcome.status
                    record.outcome = outcome
                    record.finished_at = datetime.now(timezone.utc)
                    record.done.set()
                    notification = self._deliver_locked(record)
                self._condition.notify_all()
            self._notify(notification)

    def _owned(self, session_id: str, task_id: str) -> TaskRecord:
        record = self._records.get(task_id)
        if record is None or record.spec.session_id != session_id:
            raise AgentTaskAccessError("任务不存在或不属于当前会话。")
        return record

    @staticmethod
    def _snapshot(record: TaskRecord) -> TaskSnapshot:
        outcome = record.outcome
        return TaskSnapshot(
            task_id=record.spec.task_id,
            session_id=record.spec.session_id,
            kind=record.spec.kind,
            role=record.spec.role.name if record.spec.role else None,
            status=record.status,
            delivery_mode=record.delivery_mode,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            cancel_requested=record.cancel_requested,
            token_usage=outcome.token_usage if outcome else None,
            failure_reason=outcome.failure_reason if outcome else "",
        )

    def _details(self, record: TaskRecord) -> TaskDetails:
        return TaskDetails(
            self._snapshot(record), record.outcome.result if record.outcome else ""
        )

    def _deliver_locked(self, record: TaskRecord) -> InboxItem | None:
        if record.delivery_mode != "background" or record.notification_attempted:
            return None
        assert record.outcome is not None and record.finished_at is not None
        record.notification_attempted = True
        preview, truncated = _bounded_preview(
            record.outcome.result, self._preview_chars
        )
        item = InboxItem(
            task_id=record.spec.task_id,
            session_id=record.spec.session_id,
            kind=record.spec.kind,
            role=record.spec.role.name if record.spec.role else None,
            status=record.outcome.status,
            result_preview=preview,
            result_truncated=truncated,
            failure_reason=record.outcome.failure_reason,
            token_usage=record.outcome.token_usage,
            finished_at=record.finished_at,
        )
        self._inbox[record.spec.session_id].append(item)
        return item

    def _notify(self, item: InboxItem | None) -> None:
        if item is None or self._notification_sink is None:
            return
        try:
            self._notification_sink(item)
        except Exception:
            pass


def _bounded_preview(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    marker = "\n…[结果已截断，请使用 Task get 查看完整结果]…\n"
    available = max(2, limit - len(marker))
    head = available // 2
    tail = available - head
    return value[:head] + marker + value[-tail:], True
