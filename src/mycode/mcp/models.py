from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


WarningStage = Literal[
    "connect",
    "initialize",
    "list_tools",
    "tool_validation",
    "registration",
]


@dataclass(frozen=True)
class MCPRemoteTool:
    server_name: str
    remote_name: str
    exposed_name: str
    description: str
    input_schema: dict[str, object]


@dataclass(frozen=True)
class MCPDiscoveryWarning:
    server_name: str
    stage: WarningStage
    message: str


class MCPManagerError(Exception):
    def __init__(self, reason_code: str, server_name: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.server_name = server_name
        self.user_message = message
