import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest

from mycode.teams.backends.tmux import TmuxBackend
from mycode.teams.identity import WorkerTicketManager

from team_testkit import team_store


def test_tmux_wake_verifies_pane_identity(tmp_path: Path, monkeypatch) -> None:
    store, *_ = team_store(tmp_path)
    member = next(iter(store.load("alpha").team.members.values()))
    calls = []
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tmux")
    def run(args, **kwargs):
        calls.append(tuple(args))
        if "has-session" in args:
            return subprocess.CompletedProcess(args, 1, b"", b"")
        if "display-message" in args:
            return subprocess.CompletedProcess(args, 0, b"%7 1234\n", b"")
        if "-V" in args:
            return subprocess.CompletedProcess(args, 0, b"tmux 3.4\n", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr(subprocess, "run", run)
    killed = []
    monkeypatch.setattr("os.kill", lambda pid, sig: killed.append((pid, sig)))
    backend = TmuxBackend("alpha", "repo-1", tickets=WorkerTicketManager(user_root=tmp_path))
    started = backend.start(member)
    assert started.process.tmux_pane == "%7"
    member = member.__class__(**{**member.__dict__, "process": started.process})
    assert backend.wake(member, "team_msg_0000000000000001").delivered
    assert killed and killed[0][0] == 1234


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_tmux_full_flow_uses_real_pane_and_signal(tmp_path: Path) -> None:
    store, *_ = team_store(tmp_path)
    member = next(iter(store.load("alpha").team.members.values()))
    marker = tmp_path / "worker-woke"
    ready = tmp_path / "worker-ready"
    executable = tmp_path / "fake-mycode"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import signal\n"
        "from pathlib import Path\n"
        f"marker = Path({str(marker)!r})\n"
        f"ready = Path({str(ready)!r})\n"
        "signal.signal(signal.SIGUSR1, lambda *_: marker.touch())\n"
        "ready.touch()\n"
        "while True:\n"
        "    signal.pause()\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    backend = TmuxBackend(
        "alpha",
        "repo-1",
        tickets=WorkerTicketManager(user_root=tmp_path),
        executable=str(executable),
        timeout_seconds=5,
    )

    started = backend.start(member)
    running_member = replace(member, process=started.process)
    try:
        assert started.started
        assert started.process is not None
        assert backend.inspect(running_member).running
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists()
        assert backend.wake(running_member, "team_msg_0000000000000002").delivered
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
    finally:
        assert backend.stop(running_member, 5).stopped
    assert not backend.inspect(running_member).running
