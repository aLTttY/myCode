from __future__ import annotations

import fcntl
import os
import threading
import time
from pathlib import Path

from .models import TeamError


_REGISTRY_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


class FileLock:
    def __init__(self, path: Path, *, timeout_seconds: float = 5.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        key = str(path.absolute())
        with _REGISTRY_GUARD:
            self._thread_lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
        self._descriptor: int | None = None
        self._held = False

    def acquire(self, timeout_seconds: float | None = None) -> bool:
        if self._held:
            return True
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._thread_lock.acquire(timeout=min(remaining, 0.05)):
                if remaining <= 0:
                    return False
                continue
            break
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._descriptor = descriptor
                    self._held = True
                    return True
                except BlockingIOError:
                    if time.monotonic() >= deadline:
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

    def __enter__(self) -> "FileLock":
        if not self.acquire():
            raise TeamError("lock_timeout", f"等待团队锁超时：{self.path.name}")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
