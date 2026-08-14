from pathlib import Path

from mycode.teams.locking import FileLock


def test_file_lock_times_out_and_release_is_idempotent(tmp_path: Path) -> None:
    first = FileLock(tmp_path / "team.lock", timeout_seconds=0.1)
    second = FileLock(tmp_path / "team.lock", timeout_seconds=0.02)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    first.release()
    assert second.acquire()
    second.release()
