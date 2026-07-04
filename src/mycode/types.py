from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = False
    budget_tokens: int | None = None


@dataclass(frozen=True)
class AppConfig:
    protocol: str
    model: str
    base_url: str
    api_key: str
    thinking: ThinkingConfig | None = None


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class StreamEvent:
    type: Literal["text_delta", "message_done"]
    text: str = ""


class UserFacingError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ConfigError(UserFacingError):
    pass


class ProviderError(UserFacingError):
    pass
