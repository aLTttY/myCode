from datetime import datetime, timedelta
from pathlib import Path

from mycode.sessions import SessionCatalog, SessionJournal
from mycode.types import Message


def test_catalog_selects_latest_and_cleans_expired(tmp_path: Path) -> None:
    now = datetime.now().astimezone()
    old = SessionJournal(tmp_path)
    old.append(Message(role="user", content="old"), now - timedelta(days=31))
    old.close()
    recent = SessionJournal(tmp_path)
    recent.append(Message(role="user", content="recent"), now - timedelta(hours=2))
    recent.close()

    catalog = SessionCatalog(tmp_path)
    latest = catalog.latest(now)
    cleanup = catalog.cleanup_expired(now)

    assert latest is not None and latest.summary is not None
    assert latest.summary.session_id == recent.session_id
    assert cleanup.removed == 1
    assert not old.path.exists() and recent.path.exists()
