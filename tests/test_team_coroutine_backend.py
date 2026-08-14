import threading
from pathlib import Path

from mycode.teams.backends.base import BackendProbeRequest
from mycode.teams.backends.coroutine import CoroutineBackend

from team_testkit import team_store


def test_coroutine_backend_is_single_instance_wakeable_and_stoppable(tmp_path: Path) -> None:
    store, *_ = team_store(tmp_path)
    member = next(iter(store.load("alpha").team.members.values()))
    entered = threading.Event()
    def runner(member, cancel, wake):
        entered.set()
        wake.wait(1)
        cancel.wait(1)
    backend = CoroutineBackend(runner)
    assert backend.probe(BackendProbeRequest(tmp_path)).available
    first = backend.start(member)
    assert first.started and entered.wait(1)
    assert not backend.start(member).started
    assert backend.wake(member, "message").delivered
    assert backend.stop(member, 2).stopped
    backend.close()
