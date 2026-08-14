from pathlib import Path

import pytest

from mycode.teams.identity import IdentityAuthority, WorkerTicketManager
from mycode.teams.models import TeamError

from team_testkit import team_store


def test_capabilities_are_revocable_and_not_interchangeable(tmp_path: Path) -> None:
    _store, authority, lead, members, identities = team_store(tmp_path)
    authority.validate(lead, require="lead")
    with pytest.raises(TeamError):
        authority.validate(identities["alice"], require="lead")
    authority.revoke(lead)
    with pytest.raises(TeamError, match="撤销"):
        authority.validate(lead)


def test_worker_ticket_is_0600_and_single_use(tmp_path: Path) -> None:
    store, *_ = team_store(tmp_path)
    manager = WorkerTicketManager(user_root=tmp_path)
    member = next(iter(store.load("alpha").team.members.values()))
    ticket = manager.issue("alpha", member.member_id, "repo-1")
    assert ticket.path.stat().st_mode & 0o777 == 0o600
    payload = manager.consume(
        ticket.path, ticket.secret, team_name="alpha", member_id=member.member_id,
        repository_id="repo-1",
    )
    assert payload["member_id"] == member.member_id
    with pytest.raises(TeamError):
        manager.consume(
            ticket.path, ticket.secret, team_name="alpha", member_id=member.member_id,
            repository_id="repo-1",
        )
