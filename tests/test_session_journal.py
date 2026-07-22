import json
from pathlib import Path

from mycode.sessions import SESSION_ID_RE, SessionJournal
from mycode.types import Message, ToolCall


def test_journal_appends_round_trip_records_without_meta(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.append(Message(role="user", content="你好"))
    journal.append(Message(role="assistant", content="", tool_calls=(ToolCall("1", "read_file", {"path": "a"}),)))
    journal.close()

    assert SESSION_ID_RE.fullmatch(journal.session_id)
    records = [json.loads(line) for line in journal.path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["message"]["content"] == "你好"
    assert records[1]["message"]["tool_calls"][0]["id"] == "1"
    assert list(journal.path.parent.iterdir()) == [journal.path]
