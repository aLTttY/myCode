from pathlib import Path

import pytest

from mycode.teams.binding import TeamBinding, coordinator_enabled
from mycode.teams.coordinator import CoordinatorCommandPolicy
from mycode.teams.integration import IntegrationService
from mycode.teams.models import TeamError, utc_now
from mycode.types import CoordinatorConfig, TeamConfig

from team_testkit import team_store


def test_coordinator_two_lock_requires_both() -> None:
    assert coordinator_enabled(TeamConfig(coordinator=CoordinatorConfig(True)), {"MEWCODE_COORDINATOR": "1"})[0]
    assert not coordinator_enabled(TeamConfig(coordinator=CoordinatorConfig(True)), {})[0]
    assert not coordinator_enabled(TeamConfig(), {"MEWCODE_COORDINATOR": "1"})[0]


def test_coordinator_read_command_is_scoped_and_rejects_shell(tmp_path: Path) -> None:
    store, authority, lead, *_ = team_store(tmp_path)
    integration = IntegrationService(store, authority)
    policy = CoordinatorCommandPolicy(TeamConfig(coordinator=CoordinatorConfig(True)), integration)
    binding = TeamBinding("session", "alpha", lead, True, "enabled", utc_now())
    assert policy.validate_read(("git", "status"), binding).cwd == Path("/workspace")
    with pytest.raises(TeamError):
        policy.validate_read(("git", "status", ";", "rm"), binding)
    with pytest.raises(TeamError):
        policy.validate_read(("python", "-c", "print(1)"), binding)
