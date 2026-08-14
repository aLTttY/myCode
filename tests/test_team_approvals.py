from pathlib import Path

import pytest

from mycode.teams.approvals import ApprovalService
from mycode.teams.mailbox import MailboxService
from mycode.teams.models import TaskCreateRequest, TeamError
from mycode.teams.tasks import SharedTaskService

from team_testkit import team_store


def test_approval_is_bound_to_member_task_version_and_fingerprint(tmp_path: Path) -> None:
    store, authority, lead, members, identities = team_store(tmp_path)
    tasks = SharedTaskService(store, authority)
    mailbox = MailboxService(store, authority)
    approvals = ApprovalService(store, authority, mailbox)
    task = tasks.create_task(lead, TaskCreateRequest("needs plan", assignee_id=members["alice"].member_id))
    pending = approvals.submit_plan(identities["alice"], task.task_id, "safe plan", task.revision)
    with pytest.raises(TeamError, match="fingerprint"):
        approvals.decide(
            lead, task.task_id, members["alice"].member_id, pending.plan_version,
            "approved", plan_fingerprint="b" * 64,
        )
    approved = approvals.decide(
        lead, task.task_id, members["alice"].member_id, pending.plan_version,
        "approved", plan_fingerprint=pending.plan_fingerprint,
    )
    assert approvals.effective_approval(
        "alpha", members["alice"].member_id, task.task_id,
        pending.plan_version, pending.plan_fingerprint,
    ) == approved
