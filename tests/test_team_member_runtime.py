from pathlib import Path

from mycode.teams.approvals import ApprovalService
from mycode.teams.mailbox import MailboxService
from mycode.teams.member import MemberAgentResult, TeamMemberRuntime
from mycode.teams.worktrees import TeamWorktreeManager
from mycode.types import Message

from team_testkit import team_store


class FakeAgent:
    def run(self, request):
        assert request.inbox_messages[0].content == "continue"
        return MemberAgentResult((Message("assistant", "resumed"),), "resumed")


def test_member_persists_context_acks_mail_and_becomes_idle(tmp_path: Path) -> None:
    store, authority, lead, members, identities = team_store(tmp_path)
    mailbox = MailboxService(store, authority)
    approvals = ApprovalService(store, authority, mailbox)
    delivery = mailbox.send(lead, "bob", "continue")
    runtime = TeamMemberRuntime(
        store, authority, mailbox, approvals, TeamWorktreeManager(), lambda identity: FakeAgent()
    )
    outcome = runtime.run(identities["bob"])
    assert outcome.status == "idle"
    assert mailbox.list_messages(identities["bob"]) == ()
    context = store.read_context("alpha", "bob")
    assert [item.message.content for item in context] == ["continue", "resumed"]
    assert store.load("alpha").team.members[members["bob"].member_id].lifecycle == "idle"
