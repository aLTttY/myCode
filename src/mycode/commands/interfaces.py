from __future__ import annotations

from typing import Protocol

from mycode.context.models import CompactionReport

from .models import (
    ApplicationStatus,
    MemoryStatus,
    PermissionStatus,
    RuntimeMode,
    SessionStatus,
    TokenStatus,
)


class CommandRegistrationError(Exception):
    pass


class CommandExecutionError(Exception):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class CommandUI(Protocol):
    @property
    def current_mode(self) -> RuntimeMode:
        ...

    def display_message(self, text: str, *, error: bool = False) -> None:
        ...

    def clear_screen(self) -> None:
        ...

    def send_user_message(
        self,
        text: str,
        *,
        mode_override: RuntimeMode | None = None,
    ) -> None:
        ...

    def switch_mode(self, mode: RuntimeMode) -> None:
        ...

    def compact_context(self) -> CompactionReport:
        ...

    def token_status(self) -> TokenStatus:
        ...

    def session_status(self) -> SessionStatus:
        ...

    def memory_status(self) -> MemoryStatus:
        ...

    def permission_status(self) -> PermissionStatus:
        ...

    def application_status(self) -> ApplicationStatus:
        ...

    def new_session(self) -> None:
        ...

    def refresh_status(self) -> None:
        ...
