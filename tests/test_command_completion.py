from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts.prompt import CompleteStyle

from mycode.commands.builtins import create_default_command_registry
from mycode.commands.completion import (
    SlashCommandCompleter,
    create_slash_command_key_bindings,
)


def _complete(text: str, *, cursor: int | None = None):
    document = Document(text, cursor_position=len(text) if cursor is None else cursor)
    completer = SlashCommandCompleter(create_default_command_registry())
    return list(
        completer.get_completions(
            document,
            CompleteEvent(completion_requested=True),
        )
    )


def test_single_prefix_completes_canonical_name_and_trailing_space() -> None:
    completions = _complete("/cl")

    assert len(completions) == 1
    assert completions[0].text == "/clear "
    assert completions[0].start_position == -3
    assert completions[0].display_text == "/clear"


def test_multiple_prefix_matches_preserve_registration_order_for_menu() -> None:
    completions = _complete("/s")

    assert [completion.text for completion in completions] == [
        "/session ",
        "/status ",
    ]
    assert "当前会话" in completions[0].display_meta_text


def test_complete_alias_prefers_its_canonical_command() -> None:
    assert [completion.text for completion in _complete("/p")] == ["/plan "]
    assert [completion.text for completion in _complete("/st")] == ["/status "]
    assert [completion.text for completion in _complete("/?")] == ["/help "]


def test_hidden_command_is_never_a_completion_candidate() -> None:
    assert _complete("/n") == []
    assert all(completion.text != "/new " for completion in _complete("/"))


def test_completion_only_applies_to_first_slash_command_word() -> None:
    assert _complete("status") == []
    assert _complete("prefix /st") == []
    assert _complete("/help st") == []
    assert _complete("/help\tst") == []


def test_completion_uses_only_text_before_cursor() -> None:
    completions = _complete("/cl trailing", cursor=3)

    assert [completion.text for completion in completions] == ["/clear "]


def test_help_completion_metadata_contains_argument_hint() -> None:
    completion = _complete("/h")[0]

    assert "[命令]" in completion.display_meta_text


def test_prompt_session_tab_applies_single_completion() -> None:
    with create_pipe_input() as pipe_input:
        pipe_input.send_text("/cl\t\r")
        session = PromptSession(
            input=pipe_input,
            output=DummyOutput(),
            completer=SlashCommandCompleter(create_default_command_registry()),
            key_bindings=create_slash_command_key_bindings(),
            complete_while_typing=False,
            complete_style=CompleteStyle.COLUMN,
        )

        assert session.prompt() == "/clear "


def test_prompt_session_tab_opens_multiple_completion_menu() -> None:
    with create_pipe_input() as pipe_input:
        pipe_input.send_text("/s\t\t\r")
        session = PromptSession(
            input=pipe_input,
            output=DummyOutput(),
            completer=SlashCommandCompleter(create_default_command_registry()),
            key_bindings=create_slash_command_key_bindings(),
            complete_while_typing=False,
            complete_style=CompleteStyle.COLUMN,
        )

        assert session.prompt() in {"/session ", "/status "}


def test_prompt_session_backspace_then_tab_handles_unicode_menu_metadata() -> None:
    with create_pipe_input() as pipe_input:
        pipe_input.send_text("/clx\x7f\t\r")
        session = PromptSession(
            input=pipe_input,
            output=DummyOutput(),
            completer=SlashCommandCompleter(create_default_command_registry()),
            key_bindings=create_slash_command_key_bindings(),
            complete_while_typing=False,
            complete_style=CompleteStyle.COLUMN,
        )

        assert session.prompt() == "/clear "
