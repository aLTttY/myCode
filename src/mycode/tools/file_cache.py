from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _CacheEntry:
    stat_key: tuple[int, int, int, int]
    content: str


def _stat_key(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


class FileReadCache:
    """A small per-run cache that invalidates itself when file metadata changes."""

    def __init__(self) -> None:
        self._entries: dict[Path, _CacheEntry] = {}
        self._lock = threading.RLock()

    def get(self, path: Path) -> str | None:
        resolved = path.resolve()
        with self._lock:
            entry = self._entries.get(resolved)
        if entry is None:
            return None
        try:
            current = _stat_key(resolved)
        except OSError:
            self.invalidate(resolved)
            return None
        if current != entry.stat_key:
            self.invalidate(resolved)
            return None
        return entry.content

    def put(self, path: Path, content: str) -> None:
        resolved = path.resolve()
        try:
            entry = _CacheEntry(_stat_key(resolved), content)
        except OSError:
            return
        with self._lock:
            self._entries[resolved] = entry

    def invalidate(self, path: Path) -> None:
        resolved = path.resolve()
        with self._lock:
            self._entries.pop(resolved, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
