from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from mycode.types import Message


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    path: Path
    title: str
    message_count: int
    created_at: datetime
    last_active_at: datetime
    bad_line_count: int = 0


@dataclass(frozen=True)
class SessionLoadResult:
    summary: SessionSummary | None
    messages: tuple[Message, ...]
    bad_line_count: int
    truncated_message_count: int
    gap: timedelta | None = None
    needs_time_gap_reminder: bool = False


@dataclass(frozen=True)
class SessionWarning:
    code: str
    session_id: str
    message: str


@dataclass(frozen=True)
class CleanupResult:
    removed: int = 0
    warnings: tuple[SessionWarning, ...] = ()


class SessionError(Exception):
    pass
