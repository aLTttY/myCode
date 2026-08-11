from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mycode.commands.builtins import create_default_command_registry
from mycode.commands.models import (
    ApplicationStatus,
    MemoryStatus,
    PermissionSourceStatus,
    PermissionStatus,
    SessionStatus,
    TokenStatus,
)
from mycode.commands.router import CommandDispatcher, InputRouter
from mycode.context.models import CompactionReport, ContextStatus
from mycode.types import TokenUsage


CONTEXT = ContextStatus(120, 1_000, 4, True, False)


@dataclass
class FakeCommandUI:
    mode: str = "default"
    messages: list[tuple[str, bool]] = field(default_factory=list)
    sent: list[tuple[str, str | None]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    skill_calls: list[tuple[str, str]] = field(default_factory=list)
    report: CompactionReport = field(
        default_factory=lambda: CompactionReport(
            status="success",
            trigger="manual",
            before_tokens=800,
            after_tokens=120,
            budget_tokens=700,
            summarized_messages=3,
            summary_token_usage=TokenUsage(90, 30, 120),
        )
    )

    @property
    def current_mode(self):
        return self.mode

    def display_message(self, text: str, *, error: bool = False) -> None:
        self.messages.append((text, error))

    def clear_screen(self) -> None:
        self.calls.append("clear")

    def send_user_message(self, text: str, *, mode_override=None) -> None:
        self.sent.append((text, mode_override))

    def invoke_skill(self, name: str, input_text: str) -> None:
        self.skill_calls.append((name, input_text))

    def switch_mode(self, mode) -> None:
        self.calls.append(f"mode:{mode}")
        self.mode = mode

    def compact_context(self) -> CompactionReport:
        self.calls.append("compact")
        return self.report

    def token_status(self) -> TokenStatus:
        self.calls.append("token_status")
        return TokenStatus(TokenUsage(10, 5, 15), CONTEXT)

    def session_status(self) -> SessionStatus:
        self.calls.append("session_status")
        return SessionStatus("session-1", 4, "restored", CONTEXT)

    def memory_status(self) -> MemoryStatus:
        self.calls.append("memory_status")
        return MemoryStatus(
            2,
            1,
            Path("/project/MEMORY.md"),
            Path("/user/MEMORY.md"),
            "busy",
            2,
        )

    def permission_status(self) -> PermissionStatus:
        self.calls.append("permission_status")
        return _permission_status()

    def application_status(self) -> ApplicationStatus:
        self.calls.append("application_status")
        session = SessionStatus("session-1", 4, "restored", CONTEXT)
        memory = MemoryStatus(
            2,
            1,
            Path("/project/MEMORY.md"),
            Path("/user/MEMORY.md"),
            "busy",
            2,
        )
        return ApplicationStatus(
            self.mode,
            "openai_compatible",
            "test-model",
            TokenStatus(None, CONTEXT),
            session,
            memory,
            _permission_status(),
        )

    def new_session(self) -> None:
        self.calls.append("new")

    def refresh_status(self) -> None:
        self.calls.append("refresh")


def _permission_status() -> PermissionStatus:
    return PermissionStatus(
        "default",
        "project",
        (
            PermissionSourceStatus("session", None, True, 1),
            PermissionSourceStatus("local", Path("/p/local.yaml"), False, 0),
            PermissionSourceStatus("project", Path("/p/project.yaml"), True, 2),
            PermissionSourceStatus("user", Path("/u/user.yaml"), True, 1),
        ),
    )


def _execute(text: str, ui: FakeCommandUI | None = None) -> FakeCommandUI:
    registry = create_default_command_registry()
    route = InputRouter(registry).route(text)
    assert route.kind == "command"
    assert route.invocation is not None
    target = ui or FakeCommandUI()
    CommandDispatcher(registry).dispatch(route.invocation, target)
    return target


def test_builtin_catalog_has_expected_order_metadata_and_types() -> None:
    registry = create_default_command_registry()
    commands = registry.commands(include_hidden=True)

    assert [command.name for command in commands] == [
        "help", "compact", "clear", "plan", "do", "session", "memory",
        "permission", "status", "new",
    ]
    assert len(registry.commands()) == 9
    assert commands[-1].hidden is True
    assert all(command.description and command.usage for command in commands)
    assert all(command.handler is not None for command in commands)
    assert {command.command_type for command in commands} == {"local", "ui"}


@pytest.mark.parametrize(
    ("name", "aliases"),
    [
        ("help", ("h", "?")),
        ("compact", ("cmp",)),
        ("clear", ("cls",)),
        ("plan", ("p",)),
        ("do", ("d",)),
        ("session", ("sess",)),
        ("memory", ("mem",)),
        ("permission", ("perm",)),
        ("status", ("st",)),
    ],
)
def test_builtin_names_and_aliases_resolve_case_insensitively(
    name: str, aliases: tuple[str, ...]
) -> None:
    registry = create_default_command_registry()

    canonical = registry.resolve(name.upper())
    assert canonical is not None
    assert canonical.name == name
    for alias in aliases:
        assert registry.resolve(alias.upper()) is canonical


def test_help_overview_lists_only_visible_commands() -> None:
    ui = _execute("/help")
    text = ui.messages[0][0]

    assert sum(f"/{name}" in text for name in (
        "help", "compact", "clear", "plan", "do", "session", "memory",
        "permission", "status",
    )) == 9
    assert "/new" not in text


def test_help_detail_resolves_alias_and_hidden_command() -> None:
    status_ui = _execute("/help st")
    hidden_ui = _execute("/help new")

    status_text = status_ui.messages[0][0]
    assert "命令：/status" in status_text
    assert "别名：/st" in status_text
    assert "类型：local" in status_text
    assert "用法：/status" in status_text
    assert "参数提示：无" in status_text
    assert "命令：/new" in hidden_ui.messages[0][0]


@pytest.mark.parametrize(
    "text", ["/compact now", "/clear now", "/plan now", "/do now",
             "/session now", "/memory now", "/permission now", "/status now",
             "/new now"]
)
def test_no_argument_commands_reject_arguments_without_side_effects(text: str) -> None:
    ui = _execute(text)

    assert ui.messages and ui.messages[0][1] is True
    assert "正确用法" in ui.messages[0][0]
    assert "/help" in ui.messages[0][0]
    assert ui.sent == []
    assert ui.calls == []


def test_help_rejects_multiple_arguments_without_sending() -> None:
    ui = _execute("/help one two")

    assert ui.messages[0][1] is True
    assert ui.sent == []


def test_compact_formats_context_and_summary_usage() -> None:
    ui = _execute("/compact")

    assert ui.calls == ["compact"]
    assert "before=800" in ui.messages[0][0]
    assert "after=120" in ui.messages[0][0]
    assert "summary_usage=(input=90 output=30 total=120)" in ui.messages[0][0]
    assert ui.sent == []


def test_clear_only_clears_screen() -> None:
    ui = _execute("/clear")

    assert ui.calls == ["clear"]
    assert ui.messages == []
    assert ui.sent == []


def test_plan_and_do_switch_persistent_mode_without_sending() -> None:
    ui = FakeCommandUI()

    _execute("/plan", ui)
    assert ui.mode == "plan"
    assert ui.calls == ["mode:plan", "refresh"]
    assert ui.sent == []

    ui.calls.clear()
    _execute("/do", ui)
    assert ui.mode == "default"
    assert ui.calls == ["mode:default", "refresh"]
    assert ui.sent == []


def test_session_displays_safe_summary() -> None:
    ui = _execute("/session")
    text = ui.messages[0][0]

    assert ui.calls == ["session_status"]
    assert "id=session-1" in text
    assert "origin=restored" in text
    assert "messages=4" in text
    assert "tokens=120/1000" in text


def test_memory_displays_counts_paths_and_worker_only() -> None:
    ui = _execute("/memory")
    text = ui.messages[0][0]

    assert ui.calls == ["memory_status"]
    assert "project=2" in text and "/project/MEMORY.md" in text
    assert "user=1" in text and "/user/MEMORY.md" in text
    assert "worker=busy pending=2" in text


def test_permission_displays_mode_source_priority_and_counts() -> None:
    ui = _execute("/permission")
    text = ui.messages[0][0]

    assert ui.calls == ["permission_status"]
    assert "mode=default source=project" in text
    assert "priority=session > local > project > user" in text
    assert "session loaded=yes rules=1 path=runtime" in text
    assert "project loaded=yes rules=2" in text


def test_status_marks_missing_tokens_unavailable_and_aggregates() -> None:
    ui = _execute("/status")
    text = ui.messages[0][0]

    assert ui.calls == ["application_status"]
    assert "mode=default provider=openai_compatible model=test-model" in text
    assert "permission=default" in text
    assert "session=session-1" in text
    assert "[usage] unavailable" in text
    assert "tokens=120/1000" in text
    assert "worker=busy pending=2" in text


def test_hidden_new_is_local_and_preserves_mode() -> None:
    ui = FakeCommandUI(mode="plan")

    _execute("/new", ui)

    assert ui.calls == ["new"]
    assert ui.mode == "plan"
    assert ui.sent == []
