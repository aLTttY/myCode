from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

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
