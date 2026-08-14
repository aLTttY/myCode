import subprocess
from pathlib import Path

import pytest

from mycode.teams.models import TeamError

from team_testkit import live_team


def test_long_lived_worktree_recovers_and_refuses_dirty_dispose(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(tmp_path)
    identity = members["alice"].worktree
    assert identity is not None
    recovered = service.worktrees.recover(identity)
    assert recovered.branch_ref.startswith("refs/heads/mewcode/team/alpha/")
    (Path(identity.worktree_path) / "new.txt").write_text("new", encoding="utf-8")
    with pytest.raises(TeamError, match="脏文件"):
        service.worktrees.dispose(identity)
