from __future__ import annotations

import hashlib
import json
import os
import secrets
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from .models import ActorRef, TeamError
from .paths import safe_child, team_dir, validate_member_id, validate_team_name


@dataclass(frozen=True, repr=False)
class LeadIdentity:
    team_name: str
    repository_id: str
    capability: str

    @property
    def actor_ref(self) -> ActorRef:
        return ActorRef("lead", "lead")


@dataclass(frozen=True, repr=False)
class MemberIdentity:
    team_name: str
    member_id: str
    member_name: str
    repository_id: str
    capability: str

    @property
    def actor_ref(self) -> ActorRef:
        return ActorRef("member", self.member_name, self.member_id)


ActorIdentity = LeadIdentity | MemberIdentity


class IdentityAuthority:
    """Issues unguessable process-local capabilities and validates every service call."""

    def __init__(self) -> None:
        self._active: dict[str, tuple[str, str, str | None]] = {}

    def issue_lead(self, team_name: str, repository_id: str) -> LeadIdentity:
        token = secrets.token_urlsafe(32)
        name = validate_team_name(team_name)
        self._active[token] = (name, repository_id, None)
        return LeadIdentity(name, repository_id, token)

    def issue_member(
        self, team_name: str, member_id: str, member_name: str, repository_id: str
    ) -> MemberIdentity:
        token = secrets.token_urlsafe(32)
        name = validate_team_name(team_name)
        validate_member_id(member_id)
        self._active[token] = (name, repository_id, member_id)
        return MemberIdentity(name, member_id, member_name, repository_id, token)

    def validate(self, identity: ActorIdentity, *, require: Literal["lead", "member", "either"] = "either") -> None:
        record = self._active.get(identity.capability)
        expected_member = identity.member_id if isinstance(identity, MemberIdentity) else None
        if record != (identity.team_name, identity.repository_id, expected_member):
            raise TeamError("invalid_identity", "团队身份已撤销、伪造或不匹配。")
        if require == "lead" and not isinstance(identity, LeadIdentity):
            raise TeamError("lead_required", "该操作仅允许 Team Lead。")
        if require == "member" and not isinstance(identity, MemberIdentity):
            raise TeamError("member_required", "该操作仅允许团队成员。")

    def revoke(self, identity: ActorIdentity) -> None:
        self._active.pop(identity.capability, None)

    def revoke_team(self, team_name: str) -> None:
        for token, record in tuple(self._active.items()):
            if record[0] == team_name:
                self._active.pop(token, None)


@dataclass(frozen=True)
class WorkerLaunchTicket:
    ticket_id: str
    team_name: str
    member_id: str
    repository_id: str
    expires_at: datetime
    secret_hash: str
    path: Path
    secret: str


class WorkerTicketManager:
    def __init__(self, *, user_root: Path | None = None) -> None:
        self.user_root = user_root

    def issue(
        self,
        team_name: str,
        member_id: str,
        repository_id: str,
        *,
        ttl_seconds: float = 30.0,
    ) -> WorkerLaunchTicket:
        name = validate_team_name(team_name)
        validate_member_id(member_id)
        ticket_id = f"ticket_{secrets.token_hex(16)}"
        secret = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(1.0, ttl_seconds))
        root = safe_child(team_dir(name, self.user_root), ".tickets", allow_missing=True)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = safe_child(root, f"{ticket_id}.json", allow_missing=True)
        payload = {
            "schema_version": 1,
            "ticket_id": ticket_id,
            "team_name": name,
            "member_id": member_id,
            "repository_id": repository_id,
            "expires_at": expires_at.isoformat(),
            "secret_hash": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            "secret": secret,
        }
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, json.dumps(payload, sort_keys=True).encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return WorkerLaunchTicket(
            ticket_id, name, member_id, repository_id, expires_at,
            payload["secret_hash"], path, secret,
        )

    def consume(
        self,
        path: Path,
        secret: str | None,
        *,
        team_name: str,
        member_id: str,
        repository_id: str,
    ) -> dict[str, object]:
        name = validate_team_name(team_name)
        expected_root = safe_child(team_dir(name, self.user_root), ".tickets", allow_missing=False)
        lexical = path.absolute()
        if (
            lexical.parent != expected_root.absolute()
            or re.fullmatch(r"ticket_[a-f0-9]{32}\.json", lexical.name) is None
        ):
            raise TeamError("invalid_ticket_path", "Worker 启动票据路径不在当前团队专用目录。")
        if path.is_symlink() or not path.is_file():
            raise TeamError("invalid_ticket", "Worker 启动票据不存在或不安全。")
        if path.stat().st_mode & 0o077:
            raise TeamError("ticket_permissions", "Worker 启动票据权限必须为 0600。")
        consumed = path.with_suffix(".consuming")
        try:
            os.replace(path, consumed)
        except OSError as exc:
            raise TeamError("ticket_replayed", "Worker 启动票据已消费或无法锁定。") from exc
        try:
            payload = json.loads(consumed.read_text(encoding="utf-8"))
            expires_at = datetime.fromisoformat(str(payload.get("expires_at", "")))
            supplied_secret = secret if secret is not None else payload.get("secret")
            if not isinstance(supplied_secret, str):
                raise TeamError("invalid_ticket", "Worker 启动票据缺少一次性 secret。")
            actual_hash = hashlib.sha256(supplied_secret.encode("utf-8")).hexdigest()
            if (
                payload.get("team_name") != name
                or payload.get("member_id") != validate_member_id(member_id)
                or payload.get("repository_id") != repository_id
                or payload.get("secret_hash") != actual_hash
                or expires_at.tzinfo is None
                or expires_at <= datetime.now(timezone.utc)
            ):
                raise TeamError("invalid_ticket", "Worker 启动票据已过期、被篡改或身份不匹配。")
            return payload
        finally:
            consumed.unlink(missing_ok=True)
