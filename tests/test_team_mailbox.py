from pathlib import Path

from mycode.teams.mailbox import MailboxService

from team_testkit import team_store


def test_direct_broadcast_idempotency_and_ack(tmp_path: Path) -> None:
    store, authority, lead, members, identities = team_store(tmp_path)
    mailbox = MailboxService(store, authority)
    first = mailbox.send(lead, "alice", "hello", idempotency_key="same")
    again = mailbox.send(lead, "alice", "hello", idempotency_key="same")
    assert first.message_id == again.message_id
    assert len(mailbox.list_messages(identities["alice"])) == 1
    mailbox.ack(identities["alice"], [first.message_id])
    assert mailbox.list_messages(identities["alice"]) == ()
    result = mailbox.broadcast(lead, "all")
    assert {item.recipient for item in result.deliveries} == {"alice", "bob"}
