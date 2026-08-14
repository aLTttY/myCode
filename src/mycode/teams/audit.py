from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from .locking import FileLock
from .models import AuditEvent, TeamError
from .paths import lock_path, team_dir


class AuditWriter:
    def __init__(self, *, user_root: Path | None = None, summary_chars: int = 240) -> None:
        self.user_root = user_root
        self.summary_chars = summary_chars

    def write(self, team_name: str, event: AuditEvent, *, already_locked: bool = False) -> None:
        if len(event.summary) > self.summary_chars:
            event = replace(event, summary=event.summary[: self.summary_chars])
        if already_locked:
            self._append(team_name, event)
            return
        with FileLock(lock_path(team_name, user_root=self.user_root)):
            self._append(team_name, event)

    def _append(self, team_name: str, event: AuditEvent) -> None:
        path = team_dir(team_name, self.user_root) / "audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        value = asdict(event)
        value["timestamp"] = event.timestamp.isoformat()
        line = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, line)
            os.fsync(descriptor)
        except OSError as exc:
            raise TeamError("audit_failed", "无法写入团队安全审计。") from exc
        finally:
            os.close(descriptor)


class AuditReader:
    def __init__(self, *, user_root: Path | None = None) -> None:
        self.user_root = user_root

    def read(self, team_name: str, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        path = team_dir(team_name, self.user_root) / "audit.jsonl"
        if not path.exists():
            return ()
        if path.is_symlink():
            raise TeamError("symlink_file", "审计文件不能是符号链接。")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        return tuple(rows[-max(0, limit):])
