from dataclasses import replace
from pathlib import Path

import pytest

from mycode.teams.models import RevisionSet, TeamError

from team_testkit import team_store


def test_store_round_trip_and_revision_conflict(tmp_path: Path) -> None:
    store, *_ = team_store(tmp_path)
    before = store.load("alpha")
    after = store.transact(
        "alpha", RevisionSet(team=before.team.revision),
        lambda aggregate: replace(aggregate, team=replace(aggregate.team, status="freezing")),
    )
    assert after.team.status == "freezing"
    assert after.team.revision == before.team.revision + 1
    assert store.load("alpha").team.last_transaction_id.startswith("tx_")
    with pytest.raises(TeamError, match="revision"):
        store.transact("alpha", RevisionSet(team=before.team.revision), lambda value: value)


def test_store_rejects_unknown_schema_field(tmp_path: Path) -> None:
    store, *_ = team_store(tmp_path)
    path = tmp_path / ".mycode" / "teams" / "alpha" / "team.json"
    text = path.read_text(encoding="utf-8").rstrip()
    path.write_text(text[:-1] + ',"unknown":true}\n', encoding="utf-8")
    with pytest.raises(TeamError, match="字段"):
        store.load("alpha")
