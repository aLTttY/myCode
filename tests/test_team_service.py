from pathlib import Path
import json

import pytest

from mycode.teams.models import MemberCreateRequest, TeamError

from team_testkit import live_team, role


def test_service_persists_role_snapshot_and_protects_archive(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(tmp_path)
    member = members["alice"]
    assert member.role.system_prompt == "Work carefully."
    assert member.worktree is not None and Path(member.worktree.worktree_path).is_dir()
    assert service.freeze_for_archive(lead).ready
    dirty = Path(member.worktree.worktree_path) / "dirty.txt"
    dirty.write_text("dirty", encoding="utf-8")
    readiness = service.freeze_for_archive(lead)
    assert not readiness.ready and any("dirty" in item for item in readiness.blockers)


def test_duplicate_member_name_is_rejected(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(tmp_path)
    with pytest.raises(TeamError, match="名称"):
        service.add_member(lead, MemberCreateRequest("alice", role()))


def test_successful_archive_persists_archived_status(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(tmp_path)
    revision = store.load("alpha").team.revision
    result = service.archive_team(lead, revision)
    assert not (tmp_path / ".mycode" / "teams" / "alpha").exists()
    payload = json.loads((result.path / "team.json").read_text(encoding="utf-8"))
    assert payload["status"] == "archived"
