from __future__ import annotations

import fcntl
import os
import threading
import time
from pathlib import Path

from .models import WorktreeError
from .paths import lock_path


_REGISTRY_LOCK = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


class TargetLock:
    def __init__(self, main_workspace: Path, managed_name: str) -> None:
        self.path = lock_path(main_workspace, managed_name)
        self._key = str(self.path.resolve(strict=False))
        with _REGISTRY_LOCK:
            self._thread_lock = _THREAD_LOCKS.setdefault(self._key, threading.Lock())
        self._descriptor: int | None = None
        self._held = False

    def acquire(self, timeout_seconds: float | None = None) -> bool:
        deadline = None if timeout_seconds is None else time.monotonic() + max(0.0, timeout_seconds)
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            if self._thread_lock.acquire(timeout=-1 if remaining is None else min(remaining, 0.05)):
                break
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._descriptor = descriptor
                    self._held = True
                    return True
                except BlockingIOError:
                    if deadline is not None and time.monotonic() >= deadline:
                        os.close(descriptor)
                        self._thread_lock.release()
                        return False
                    time.sleep(0.01)
        except Exception:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        if not self._held:
            return
        descriptor = self._descriptor
        self._descriptor = None
        self._held = False
        try:
            if descriptor is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
        finally:
            self._thread_lock.release()

    def __enter__(self) -> "TargetLock":
        if not self.acquire():
            raise WorktreeError("lock_timeout", "无法取得 Worktree 目标锁。")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
