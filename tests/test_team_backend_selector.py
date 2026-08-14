from pathlib import Path

import pytest

from mycode.teams.backends.base import BackendProbeResult
from mycode.teams.backends.selector import TeamBackendSelector
from mycode.teams.models import TeamError


class FakeBackend:
    def __init__(self, name, available, message=""):
        self.name, self.available, self.message = name, available, message
    def probe(self, request):
        return BackendProbeResult(self.name, self.available, "probe", self.message)


def test_auto_prefers_tmux_and_reports_coroutine_fallback(tmp_path: Path) -> None:
    tmux = FakeBackend("tmux", True)
    coroutine = FakeBackend("coroutine", True)
    assert TeamBackendSelector(tmux, coroutine).select("auto", tmp_path).actual_backend == "tmux"
    fallback = TeamBackendSelector(FakeBackend("tmux", False, "missing"), coroutine).select("auto", tmp_path)
    assert fallback.actual_backend == "coroutine"
    assert "missing" in fallback.fallback_reason


def test_explicit_tmux_never_silently_falls_back(tmp_path: Path) -> None:
    selector = TeamBackendSelector(FakeBackend("tmux", False, "missing"), FakeBackend("coroutine", True))
    with pytest.raises(TeamError, match="显式"):
        selector.select("tmux", tmp_path)
