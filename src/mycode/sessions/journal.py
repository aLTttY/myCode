from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from mycode.types import Message

from .models import SessionError


SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def new_session_id(now: datetime | None = None) -> str:
    current = now or datetime.now().astimezone()
    return f"{current:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


class SessionJournal:
    def __init__(self, workspace_root: Path, session_id: str | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.root = self.workspace_root / ".mycode" / "sessions"
        self._ensure_root()
        if session_id is None:
            for _ in range(100):
                candidate = new_session_id()
                path = self.root / f"{candidate}.jsonl"
                if not path.exists():
                    session_id = candidate
                    break
            else:
                raise SessionError("无法生成不冲突的会话标识。")
        if not SESSION_ID_RE.fullmatch(session_id):
            raise SessionError("会话标识格式非法。")
        self.session_id = session_id
        self.path = self.root / f"{session_id}.jsonl"
        if self.path.is_symlink():
            raise SessionError("会话日志不能是符号链接。")
        try:
            self._handle = self.path.open("a", encoding="utf-8")
        except OSError as exc:
            raise SessionError(f"无法打开会话日志（{type(exc).__name__}）。") from exc
        self._closed = False

    def append(self, message: Message, timestamp: datetime | None = None) -> None:
        if self._closed:
            raise SessionError("会话日志已经关闭。")
        record = {
            "version": 1,
            "timestamp": (timestamp or datetime.now().astimezone()).isoformat(timespec="microseconds"),
            "type": "message",
            "message": asdict(message),
        }
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            self._handle.write(line)
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except (OSError, TypeError, ValueError) as exc:
            raise SessionError(f"会话记录写入失败（{type(exc).__name__}）。") from exc

    def close(self) -> str | None:
        if self._closed:
            return None
        self._closed = True
        try:
            self._handle.flush()
            self._handle.close()
        except OSError as exc:
            return f"会话日志关闭失败（{type(exc).__name__}）。"
        return None

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise SessionError("会话目录不能是符号链接。")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            resolved = self.root.resolve()
            resolved.relative_to(self.workspace_root)
        except (OSError, ValueError) as exc:
            raise SessionError("会话目录越过工作区边界或无法创建。") from exc
