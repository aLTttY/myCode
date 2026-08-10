from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings

from .registry import CommandRegistry


class SlashCommandCompleter(Completer):
    def __init__(self, registry: CommandRegistry) -> None:
        self._registry = registry

    def get_completions(
        self,
        document: Document,
        complete_event: object,
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        if any(character.isspace() for character in text):
            return

        fragment = text[1:]
        for command in self._registry.completion_candidates(fragment):
            meta = command.description
            if command.argument_hint:
                meta = f"{meta}  {command.argument_hint}"
            yield Completion(
                text=f"/{command.name} ",
                start_position=-len(text),
                display=f"/{command.name}",
                display_meta=meta,
            )


def create_slash_command_key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("tab")
    def _complete(event) -> None:
        buffer = event.current_buffer
        if buffer.complete_state is not None:
            buffer.complete_next()
            return
        if buffer.completer is None:
            return
        completions = list(
            buffer.completer.get_completions(
                buffer.document,
                CompleteEvent(completion_requested=True),
            )
        )
        if len(completions) == 1:
            buffer.apply_completion(completions[0])
        elif completions:
            # Candidates are registry-local and already materialized, so set the
            # menu synchronously. This keeps a rapid second Tab deterministic.
            buffer._set_completions(completions)

    return bindings
