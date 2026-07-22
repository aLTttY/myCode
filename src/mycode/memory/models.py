from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


MemoryCategory = Literal["user_preference", "correction_feedback", "project_knowledge", "reference"]
MemoryScope = Literal["user", "project"]
MemoryAction = Literal["ignore", "create", "update"]


@dataclass(frozen=True)
class MemoryNote:
    id: str
    category: MemoryCategory
    scope: MemoryScope
    importance: int
    created_at: datetime
    updated_at: datetime
    source_session: str
    title: str
    summary: str
    body: str


@dataclass(frozen=True)
class MemoryIndexEntry:
    note_id: str
    filename: str
    category: MemoryCategory
    importance: int
    updated_at: datetime
    title: str
    summary: str


@dataclass(frozen=True)
class MemoryOperation:
    action: MemoryAction
    scope: MemoryScope = "project"
    category: MemoryCategory = "project_knowledge"
    importance: int = 3
    title: str = ""
    summary: str = ""
    body: str = ""
    target_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class MemoryDecision:
    operations: tuple[MemoryOperation, ...]


@dataclass(frozen=True)
class TurnSnapshot:
    session_id: str
    user_text: str
    assistant_text: str
    tool_summaries: tuple[str, ...] = ()
    project_index: str = ""
    user_index: str = ""


@dataclass(frozen=True)
class MemoryNotice:
    code: str
    message: str


@dataclass
class MemoryJob:
    job_id: str
    snapshot: TurnSnapshot
    cancelled: threading.Event = field(default_factory=threading.Event)
