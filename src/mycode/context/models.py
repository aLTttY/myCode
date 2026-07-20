from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mycode.types import ContextConfig

if TYPE_CHECKING:
    from mycode.providers.base import ChatRequest
    from mycode.types import Message


AUTO_RESERVE_TOKENS = 13_000
MANUAL_RESERVE_TOKENS = 3_000
RECENT_TARGET_TOKENS = 10_000
RECENT_MIN_MESSAGES = 5
PREVIEW_CHARS = 1_000
MAX_SUMMARY_FAILURES = 3


@dataclass(frozen=True)
class TokenAnchor:
    input_tokens: int
    snapshot_score: int


@dataclass(frozen=True)
class StoredContextReference:
    path: str
    kind: Literal["tool_result", "user_message"]
    original_chars: int
    approximate_tokens: int
    source_id: str


@dataclass(frozen=True)
class ContextUnit:
    messages: tuple[Message, ...]

    @property
    def message_count(self) -> int:
        return len(self.messages)


@dataclass(frozen=True)
class ManagedMessage:
    sequence: int
    message: Message
    complete_content: str = ""
    batch_id: str = ""
    source_id: str = ""
    offloaded: bool = False


@dataclass(frozen=True)
class SummaryOutput:
    summary: str
    headings: tuple[str, ...]


CompactionStatus = Literal["success", "failed", "not_needed", "tripped"]
CompactionTrigger = Literal["automatic", "manual"]


@dataclass(frozen=True)
class CompactionReport:
    status: CompactionStatus
    trigger: CompactionTrigger
    before_tokens: int
    after_tokens: int
    budget_tokens: int
    offloaded_tool_results: int = 0
    offloaded_user_messages: int = 0
    summarized_messages: int = 0
    stage: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PreparedContext:
    allowed: bool
    request: ChatRequest
    report: CompactionReport


@dataclass(frozen=True)
class ContextState:
    messages: tuple[Message, ...] = ()
    summary: str = ""
    boundary: str = ""
    consecutive_summary_failures: int = 0
    automatic_summary_tripped: bool = False
    token_anchor: TokenAnchor | None = None
