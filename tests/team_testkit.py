from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from mycode.teams.identity import IdentityAuthority
from mycode.teams.models import (
    AgentRoleSnapshot,
    RevisionSet,
    TeamAggregate,
    TeamCreateRequest,
    TeamMemberSnapshot,
    utc_now,
)
from mycode.teams.storage import FileTeamStore
from mycode.teams.service import TeamService
from mycode.teams.models import MemberCreateRequest
from mycode.worktrees.paths import filesystem_repository_id


def role(name: str = "builder") -> AgentRoleSnapshot:
    return AgentRoleSnapshot(
        name, "build things", (), (), "inherit", 4, "default",
        "Work carefully.", "project", f"test:{name}", "a" * 64, "worktree",
    )


def team_store(
    tmp_path: Path,
    *,
    members: tuple[str, ...] = ("alice", "bob"),
    approval_names: tuple[str, ...] = ("alice",),
):
    store = FileTeamStore(user_root=tmp_path)
    store.create(TeamCreateRequest("alpha", "repo-1", "/workspace", "refs/heads/main"))
    now = utc_now()
    created = {}
    def mutation(aggregate: TeamAggregate) -> TeamAggregate:
        snapshots = {}
        for index, name in enumerate(members, start=1):
            member_id = f"team_member_{index:016x}"
            snapshots[member_id] = TeamMemberSnapshot(
                member_id, name, 1, role(), True, name in approval_names, "coroutine",
                None, (), "idle", None, None, None, 0, 0, now, now,
            )
            created[name] = snapshots[member_id]
        return replace(aggregate, team=replace(aggregate.team, members=MappingProxyType(snapshots)))
    store.transact("alpha", RevisionSet(), mutation)
    authority = IdentityAuthority()
    lead = authority.issue_lead("alpha", "repo-1")
    identities = {
        name: authority.issue_member("alpha", member.member_id, name, "repo-1")
        for name, member in created.items()
    }
    return store, authority, lead, created, identities


def git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(("git", "init", "-b", "main"), cwd=path, check=True, capture_output=True)
    subprocess.run(("git", "config", "user.email", "test@example.com"), cwd=path, check=True)
    subprocess.run(("git", "config", "user.name", "Test"), cwd=path, check=True)
    (path / ".gitignore").write_text(".mycode/worktrees/\n", encoding="utf-8")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(("git", "add", "."), cwd=path, check=True)
    subprocess.run(("git", "commit", "-m", "base"), cwd=path, check=True, capture_output=True)
    return path


def live_team(
    tmp_path: Path,
    names: tuple[str, ...] = ("alice",),
    approval_names: tuple[str, ...] = (),
):
    repo = git_repo(tmp_path / "repo")
    store = FileTeamStore(user_root=tmp_path)
    authority = IdentityAuthority()
    service = TeamService(store, authority)
    service.create_team("alpha", repo)
    repository_id = filesystem_repository_id(repo)
    lead = authority.issue_lead("alpha", repository_id)
    members = {
        name: service.add_member(
            lead, MemberCreateRequest(
                name, role(), writable=True, approval_required=name in approval_names,
                backend_preference="coroutine",
            )
        )
        for name in names
    }
    identities = {
        name: authority.issue_member("alpha", member.member_id, member.name, repository_id)
        for name, member in members.items()
    }
    return repo, store, authority, service, lead, members, identities
