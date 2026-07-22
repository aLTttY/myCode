from datetime import datetime
from pathlib import Path

from mycode.sessions import SessionJournal, SessionLoader
from mycode.types import Message, ToolCall


def test_loader_skips_bad_line_and_truncates_incomplete_tool_unit(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    when = datetime.now().astimezone()
    journal.append(Message(role="user", content="title"), when)
    journal.append(Message(role="assistant", content="", tool_calls=(ToolCall("1", "x", {}),)), when)
    journal.close()
    with journal.path.open("a", encoding="utf-8") as handle:
        handle.write("{bad}\n")

    result = SessionLoader().load(journal.path, when)

    assert result.bad_line_count == 1
    assert [message.role for message in result.messages] == ["user"]
    assert result.truncated_message_count == 1
    assert result.summary is not None and result.summary.title == "title"


def test_loader_keeps_complete_tool_unit(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.append(Message(role="user", content="go"))
    journal.append(Message(role="assistant", content="", tool_calls=(ToolCall("1", "x", {}),)))
    journal.append(Message(role="tool", content="ok", tool_call_id="1"))
    journal.close()

    result = SessionLoader().load(journal.path)

    assert [message.role for message in result.messages] == ["user", "assistant", "tool"]
