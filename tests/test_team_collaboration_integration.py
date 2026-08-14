from pathlib import Path

from mycode.teams.approvals import ApprovalService
from mycode.teams.mailbox import MailboxService
from mycode.teams.models import TaskCreateRequest
from mycode.teams.tasks import SharedTaskService

from team_testkit import live_team


def test_coroutine_full_flow(tmp_path: Path) -> None:
    repo, store, authority, service, lead, members, identities = live_team(
        tmp_path, approval_names=("alice",)
    )
    tasks = SharedTaskService(store, authority)
    mailbox = MailboxService(store, authority)
    approvals = ApprovalService(store, authority, mailbox)
    task = tasks.create_task(lead, TaskCreateRequest("flow", assignee_id=members["alice"].member_id))
    plan = approvals.submit_plan(identities["alice"], task.task_id, "inspect then edit", task.revision)
    approvals.decide(
        lead, task.task_id, members["alice"].member_id, plan.plan_version,
        "approved", plan_fingerprint=plan.plan_fingerprint,
    )
    delivery = mailbox.send(lead, "alice", "start now", idempotency_key="assignment")
    assert any(view.message.message_id == delivery.message_id for view in mailbox.list_messages(identities["alice"]))
