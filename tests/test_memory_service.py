import json
import threading
from pathlib import Path

from mycode.memory import MemoryService, MemoryStore, TurnSnapshot
from mycode.types import StreamEvent


class Provider:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls = []

    def stream_chat(self, request):
        self.calls.append(request)
        yield StreamEvent(type="text_delta", text=f"<memory_update>{json.dumps(self.response)}</memory_update>")
        yield StreamEvent(type="message_done")


def test_memory_service_creates_note_with_no_tools(tmp_path: Path) -> None:
    provider = Provider({"operations": [{
        "action": "create", "scope": "project", "category": "project_knowledge", "importance": 3,
        "title": "Stack", "summary": "Python", "body": "Uses Python",
    }]})
    store = MemoryStore(tmp_path, tmp_path / "home" / ".mycode")

    notices = MemoryService(provider, store).process(TurnSnapshot("20260721-100000-abcd", "u", "a"), threading.Event())

    assert notices[0].code == "updated"
    assert provider.calls[0].tools == ()
    assert len(store.list_notes("project")) == 1
