from __future__ import annotations

import secrets
import threading
from dataclasses import replace
from types import MappingProxyType
from typing import Protocol

from mycode.types import TeamConfig

from .identity import ActorIdentity, IdentityAuthority, LeadIdentity, MemberIdentity
from .models import (
    AckResult,
    BroadcastResult,
    DeliveryResult,
    MailboxAck,
    MailboxLease,
    MailboxMessage,
    MailboxMessageView,
    RevisionSet,
    TeamAggregate,
    TeamError,
    utc_now,
)
from .protocols import ProtocolPayload, protocol_dict
from .storage import FileTeamStore


class WakeNotifier(Protocol):
    def wake(self, team_name: str, member_id: str, message_id: str) -> str: ...


class NullWakeNotifier:
    def wake(self, team_name: str, member_id: str, message_id: str) -> str:
        return ""


class MailboxService:
    def __init__(
        self,
        store: FileTeamStore,
        authority: IdentityAuthority,
        config: TeamConfig | None = None,
        *,
        notifier: WakeNotifier | None = None,
    ) -> None:
        self.store = store
        self.authority = authority
        self.config = config or store.config
        self.notifier = notifier or NullWakeNotifier()
        self._leases: dict[str, tuple[ActorIdentity, tuple[str, ...]]] = {}
        self._lease_lock = threading.Lock()

    def send(
        self,
        identity: ActorIdentity,
        recipient: str,
        body: str,
        protocol: ProtocolPayload | dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> DeliveryResult:
        self.authority.validate(identity)
        text = self._validate_body(body)
        aggregate = self.store.load(identity.team_name)
        recipient_name, member_id = self._resolve(aggregate, recipient)
        existing = self._by_idempotency(identity.team_name, recipient_name, idempotency_key)
        if existing is not None:
            return DeliveryResult(existing.message_id, recipient_name, existing.sequence)
        message = MailboxMessage(
            schema_version=1,
            record_type="message",
            sequence=0,
            message_id=f"team_msg_{secrets.token_hex(8)}",
            sender=identity.actor_ref,
            body=text,
            timestamp=utc_now(),
            read=False,
            summary=self._summary(text),
            protocol=protocol_dict(protocol),
            idempotency_key=idempotency_key or f"auto_{secrets.token_hex(16)}",
        )
        persisted = self.store.append_mailbox_record(identity.team_name, recipient_name, message)
        assert isinstance(persisted, MailboxMessage)
        warning = ""
        if member_id is not None:
            try:
                warning = self.notifier.wake(identity.team_name, member_id, persisted.message_id)
            except Exception as exc:
                warning = f"消息已持久化，但唤醒成员失败：{type(exc).__name__}"
        return DeliveryResult(persisted.message_id, recipient_name, persisted.sequence, warning)

    def broadcast(
        self,
        identity: ActorIdentity,
        body: str,
        protocol: ProtocolPayload | dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> BroadcastResult:
        self.authority.validate(identity)
        aggregate = self.store.load(identity.team_name)
        sender_name = identity.member_name if isinstance(identity, MemberIdentity) else "lead"
        recipients = ["lead", *(member.name for member in aggregate.team.members.values())]
        deliveries = []
        for recipient in recipients:
            if recipient == sender_name:
                continue
            key = None if idempotency_key is None else f"{idempotency_key}:{recipient}"
            deliveries.append(self.send(identity, recipient, body, protocol, key))
        return BroadcastResult(tuple(deliveries))

    def list_messages(
        self,
        identity: ActorIdentity,
        unread_only: bool = True,
        limit: int | None = None,
    ) -> tuple[MailboxMessageView, ...]:
        self.authority.validate(identity)
        mailbox_name = self._identity_name(identity)
        records = self.store.read_mailbox(identity.team_name, mailbox_name)
        acknowledged = {record.message_id for record in records if isinstance(record, MailboxAck)}
        views = tuple(
            MailboxMessageView(record, record.message_id in acknowledged)
            for record in records if isinstance(record, MailboxMessage)
            and (not unread_only or record.message_id not in acknowledged)
        )
        max_items = self.config.mailbox_batch_size if limit is None else min(limit, self.config.mailbox_batch_size)
        return views[:max(0, max_items)]

    def get_message(self, identity: ActorIdentity, message_id: str) -> MailboxMessageView:
        for view in self.list_messages(identity, unread_only=False, limit=self.config.mailbox_batch_size):
            if view.message.message_id == message_id:
                return view
        raise TeamError("message_not_found", "邮箱消息不存在。")

    def ack(self, identity: ActorIdentity, message_ids: tuple[str, ...] | list[str]) -> AckResult:
        self.authority.validate(identity)
        mailbox_name = self._identity_name(identity)
        records = self.store.read_mailbox(identity.team_name, mailbox_name)
        messages = {record.message_id for record in records if isinstance(record, MailboxMessage)}
        already = {record.message_id for record in records if isinstance(record, MailboxAck)}
        unknown = sorted(set(message_ids) - messages)
        if unknown:
            raise TeamError("message_not_found", f"邮箱消息不存在：{', '.join(unknown)}")
        sequence = max((record.sequence for record in records), default=0)
        acknowledged: list[str] = []
        for message_id in dict.fromkeys(message_ids):
            if message_id in already:
                acknowledged.append(message_id)
                continue
            persisted = self.store.append_mailbox_record(identity.team_name, mailbox_name, MailboxAck(
                1, "ack", 0, message_id, identity.actor_ref, utc_now()
            ))
            sequence = persisted.sequence
            acknowledged.append(message_id)
        return AckResult(tuple(acknowledged))

    def reserve_unread(self, identity: ActorIdentity, limit: int | None = None) -> MailboxLease:
        messages = self.list_messages(identity, unread_only=True, limit=limit)
        lease_id = f"lease_{secrets.token_hex(16)}"
        with self._lease_lock:
            self._leases[lease_id] = (identity, tuple(view.message.message_id for view in messages))
        return MailboxLease(lease_id, messages)

    def commit_lease(
        self, identity: ActorIdentity, lease_id: str, context_sequence: int
    ) -> AckResult:
        self.authority.validate(identity)
        with self._lease_lock:
            lease = self._leases.pop(lease_id, None)
        if lease is None or lease[0].capability != identity.capability:
            raise TeamError("invalid_lease", "邮箱 lease 不存在、过期或身份不匹配。")
        leased_messages = {
            view.message.message_id: view.message.sequence
            for view in self.list_messages(identity, unread_only=False, limit=self.config.mailbox_batch_size)
            if view.message.message_id in lease[1]
        }
        result = self.ack(identity, list(lease[1]))
        if isinstance(identity, MemberIdentity):
            def mutation(aggregate: TeamAggregate) -> TeamAggregate:
                member = aggregate.team.members.get(identity.member_id)
                if member is None:
                    raise TeamError("member_not_found", "团队成员不存在。")
                cursor = max(leased_messages.values(), default=member.mailbox_cursor)
                members = dict(aggregate.team.members)
                members[identity.member_id] = replace(
                    member,
                    mailbox_cursor=max(member.mailbox_cursor, cursor),
                    context_sequence=max(member.context_sequence, context_sequence),
                    revision=member.revision + 1,
                    updated_at=utc_now(),
                )
                return replace(aggregate, team=replace(aggregate.team, members=MappingProxyType(members)))
            self.store.transact(identity.team_name, RevisionSet(), mutation)
        return result

    def release_lease(self, identity: ActorIdentity, lease_id: str) -> None:
        self.authority.validate(identity)
        with self._lease_lock:
            lease = self._leases.get(lease_id)
            if lease is not None and lease[0].capability == identity.capability:
                self._leases.pop(lease_id, None)

    def _resolve(self, aggregate: TeamAggregate, recipient: str) -> tuple[str, str | None]:
        if recipient == "lead":
            return "lead", None
        matches = [member for member in aggregate.team.members.values() if member.name == recipient or member.member_id == recipient]
        if len(matches) != 1:
            raise TeamError("recipient_not_found", "收件人未知或名称不唯一。")
        return matches[0].name, matches[0].member_id

    def _by_idempotency(self, team_name: str, recipient: str, key: str | None) -> MailboxMessage | None:
        if key is None:
            return None
        if not key or len(key) > 200:
            raise TeamError("invalid_idempotency_key", "消息幂等键为空或过长。")
        for record in self.store.read_mailbox(team_name, recipient):
            if isinstance(record, MailboxMessage) and record.idempotency_key == key:
                return record
        return None

    def _validate_body(self, body: str) -> str:
        if not isinstance(body, str) or not body.strip() or len(body) > self.config.max_message_chars:
            raise TeamError("invalid_message", "消息正文为空或超过配置上限。")
        return body

    def _summary(self, body: str) -> str:
        compact = " ".join(body.split())
        return compact[: self.config.message_summary_chars]

    @staticmethod
    def _identity_name(identity: ActorIdentity) -> str:
        return identity.member_name if isinstance(identity, MemberIdentity) else "lead"
