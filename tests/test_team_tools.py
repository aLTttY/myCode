from pathlib import Path

from mycode.teams.approvals import ApprovalService
from mycode.teams.binding import TeamBinding
from mycode.teams.coordinator import CoordinatorCommandPolicy
from mycode.teams.integration import IntegrationService
from mycode.teams.mailbox import MailboxService
from mycode.teams.service import TeamService
from mycode.teams.tasks import SharedTaskService
from mycode.teams.tools import TeamToolRegistryProvider
from mycode.teams.models import utc_now
from mycode.tools.registry import create_default_registry
from mycode.types import CoordinatorConfig, TeamConfig

from team_testkit import role, team_store


def test_team_tools_are_injected_only_by_identity_and_coordinator_removes_writes(tmp_path: Path) -> None:
    store, authority, lead, members, identities = team_store(tmp_path)
    tasks = SharedTaskService(store, authority)
    mailbox = MailboxService(store, authority)
    approvals = ApprovalService(store, authority, mailbox)
    integration = IntegrationService(store, authority)
    config = TeamConfig(coordinator=CoordinatorConfig(True))
    provider = TeamToolRegistryProvider(
        TeamService(store, authority), tasks, mailbox, approvals, integration,
        lambda name: role(name), CoordinatorCommandPolicy(config, integration),
    )
    base = create_default_registry()
    assert set(provider.for_member(base, identities["alice"], ("read_file",)).names()) == {"read_file", "SharedTask", "Mailbox"}
    binding = TeamBinding("s", "alpha", lead, True, "enabled", utc_now())
    names = set(provider.for_lead(base, binding, "default").names())
    assert {"TeamMember", "SharedTask", "Mailbox", "TeamIntegrate", "CoordinatorCommand"} <= names
    assert {"write_file", "edit_file", "run_command"}.isdisjoint(names)
