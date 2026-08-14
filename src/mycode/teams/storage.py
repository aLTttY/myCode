from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mycode.types import Message, TeamConfig, ToolCall

from .locking import FileLock
from .models import (
    SCHEMA_VERSION,
    ActorRef,
    AgentRoleSnapshot,
    ApprovalRecord,
    AuditEvent,
    BackendDiagnostic,
    IntegrationRecord,
    MailboxAck,
    MailboxMessage,
    MailboxRecord,
    MemberContextRecord,
    MemberProcessIdentity,
    RevisionSet,
    SharedTaskRecord,
    TaskWorkEntry,
    TeamAggregate,
    TeamCreateRequest,
    TeamError,
    TeamMemberSnapshot,
    TeamSnapshot,
    TeamWorktreeIdentity,
    VerificationResult,
    utc_now,
)
from .paths import context_path, lock_path, mailbox_path, safe_child, team_dir, validate_team_name


_SNAPSHOT_FILES = ("team.json", "tasks.json", "approvals.json", "integrations.json")


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TeamError("naive_datetime", "持久化时间必须包含时区。")
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TeamError("unsupported_value", f"无法持久化类型：{type(value).__name__}")


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TeamError("duplicate_json_key", f"JSON 包含重复字段：{key}")
        result[key] = value
    return result


def _loads(raw: str, *, label: str) -> object:
    try:
        return json.loads(raw, object_pairs_hook=_object_pairs)
    except TeamError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise TeamError("invalid_json", f"{label} 不是有效 JSON。") from exc


def _strict(value: object, required: set[str], *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TeamError("invalid_schema", f"{label} 必须是 JSON 对象。")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing or unknown:
        detail = f"缺少 {missing}" if missing else f"未知 {unknown}"
        raise TeamError("invalid_schema", f"{label} 字段不匹配：{detail}。")
    return value


def _dt(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise TeamError("invalid_datetime", f"{label} 必须是带时区时间。")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TeamError("invalid_datetime", f"{label} 不是有效 ISO 8601 时间。") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise TeamError("invalid_datetime", f"{label} 必须包含时区。")
    return result


def _actor(value: object) -> ActorRef:
    item = _strict(value, {"kind", "name", "member_id"}, label="actor")
    kind = _literal(item["kind"], {"lead", "member", "system"}, "actor.kind")
    name = _nonempty(item["name"], "actor.name")
    member_id = item["member_id"] if isinstance(item["member_id"], str) else None
    if (kind == "member") != (member_id is not None):
        raise TeamError("invalid_schema", "actor.member_id 与 actor.kind 不匹配。")
    return ActorRef(kind, name, member_id)  # type: ignore[arg-type]


def _role(value: object) -> AgentRoleSnapshot:
    keys = {
        "name", "description", "allowed_tools", "denied_tools", "model", "max_iterations",
        "permission_mode", "system_prompt", "source", "source_id", "fingerprint", "isolation",
    }
    item = _strict(value, keys, label="member.role")
    return AgentRoleSnapshot(
        name=str(item["name"]),
        description=str(item["description"]),
        allowed_tools=_string_tuple(item["allowed_tools"], "allowed_tools"),
        denied_tools=_string_tuple(item["denied_tools"], "denied_tools"),
        model=_literal(item["model"], {"inherit", "haiku", "sonnet", "opus"}, "role.model"),  # type: ignore[arg-type]
        max_iterations=_int(item["max_iterations"], "max_iterations"),
        permission_mode=_literal(item["permission_mode"], {"inherit", "default", "strict"}, "role.permission_mode"),  # type: ignore[arg-type]
        system_prompt=str(item["system_prompt"]),
        source=_literal(item["source"], {"project", "user", "builtin", "plugin"}, "role.source"),  # type: ignore[arg-type]
        source_id=str(item["source_id"]),
        fingerprint=str(item["fingerprint"]),
        isolation=_literal(item["isolation"], {"shared", "worktree"}, "role.isolation"),  # type: ignore[arg-type]
    )


def _worktree(value: object) -> TeamWorktreeIdentity | None:
    if value is None:
        return None
    keys = {item.name for item in fields(TeamWorktreeIdentity)}
    item = _strict(value, keys, label="member.worktree")
    return TeamWorktreeIdentity(
        schema_version=_schema(item["schema_version"]),
        repository_id=str(item["repository_id"]), team_name=str(item["team_name"]),
        member_id=str(item["member_id"]), managed_name=str(item["managed_name"]),
        main_workspace=str(item["main_workspace"]), worktree_path=str(item["worktree_path"]),
        branch_ref=str(item["branch_ref"]), base_commit=str(item["base_commit"]),
        integrated_commit=str(item["integrated_commit"]), expected_gitdir=str(item["expected_gitdir"]),
        initialization_fingerprint=str(item["initialization_fingerprint"]),
        lifecycle_state=_literal(item["lifecycle_state"], {"creating", "active", "retained", "cleanup_failed"}, "worktree.lifecycle_state"),  # type: ignore[arg-type]
        created_at=_dt(item["created_at"], "worktree.created_at"),
        last_active_at=_dt(item["last_active_at"], "worktree.last_active_at"),
    )


def _process(value: object) -> MemberProcessIdentity | None:
    if value is None:
        return None
    keys = {item.name for item in fields(MemberProcessIdentity)}
    item = _strict(value, keys, label="member.process")
    pane_pid = item["pane_pid"]
    return MemberProcessIdentity(
        backend=_literal(item["backend"], {"tmux", "coroutine"}, "process.backend"),  # type: ignore[arg-type]
        runtime_token=str(item["runtime_token"]), tmux_socket=str(item["tmux_socket"]),
        tmux_session=str(item["tmux_session"]), tmux_window=str(item["tmux_window"]),
        tmux_pane=str(item["tmux_pane"]), pane_pid=pane_pid if type(pane_pid) is int else None,
    )


def _member(value: object) -> TeamMemberSnapshot:
    keys = {item.name for item in fields(TeamMemberSnapshot)}
    item = _strict(value, keys, label="member")
    diagnostics = []
    for raw in _list(item["backend_diagnostics"], "backend_diagnostics"):
        diagnostic = _strict(raw, {"backend", "available", "code", "message"}, label="backend diagnostic")
        diagnostics.append(BackendDiagnostic(
            _literal(diagnostic["backend"], {"tmux", "coroutine"}, "diagnostic.backend"),
            _bool(diagnostic["available"], "diagnostic.available"),
            str(diagnostic["code"]), str(diagnostic["message"]),  # type: ignore[arg-type]
        ))
    return TeamMemberSnapshot(
        member_id=str(item["member_id"]), name=str(item["name"]),
        revision=_int(item["revision"], "member.revision"), role=_role(item["role"]),
        writable=_bool(item["writable"], "member.writable"),
        approval_required=_bool(item["approval_required"], "member.approval_required"),
        backend_preference=_literal(item["backend_preference"], {"auto", "tmux", "coroutine"}, "member.backend_preference"),  # type: ignore[arg-type]
        actual_backend=(None if item["actual_backend"] is None else _literal(item["actual_backend"], {"tmux", "coroutine"}, "member.actual_backend")),  # type: ignore[arg-type]
        backend_diagnostics=tuple(diagnostics), lifecycle=_literal(item["lifecycle"], {"provisioning", "offline", "starting", "running", "waiting_approval", "blocked", "idle", "stopping", "failed", "needs_attention"}, "member.lifecycle"),  # type: ignore[arg-type]
        current_task_id=item["current_task_id"] if isinstance(item["current_task_id"], str) else None,
        worktree=_worktree(item["worktree"]), process=_process(item["process"]),
        mailbox_cursor=_int(item["mailbox_cursor"], "member.mailbox_cursor"),
        context_sequence=_int(item["context_sequence"], "member.context_sequence"),
        created_at=_dt(item["created_at"], "member.created_at"),
        updated_at=_dt(item["updated_at"], "member.updated_at"),
    )


def _team(value: object) -> TeamSnapshot:
    keys = {item.name for item in fields(TeamSnapshot)}
    item = _strict(value, keys, label="team")
    raw_members = item["members"]
    if not isinstance(raw_members, dict):
        raise TeamError("invalid_schema", "team.members 必须是对象。")
    members = {str(key): _member(raw) for key, raw in raw_members.items()}
    return TeamSnapshot(
        schema_version=_schema(item["schema_version"]), revision=_int(item["revision"], "team.revision"),
        name=validate_team_name(str(item["name"])), status=_literal(item["status"], {"active", "freezing", "archive_ready", "archived"}, "team.status"),  # type: ignore[arg-type]
        lead_name=str(item["lead_name"]), repository_id=str(item["repository_id"]),
        workspace_root=str(item["workspace_root"]), lead_branch_ref=str(item["lead_branch_ref"]),
        created_at=_dt(item["created_at"], "team.created_at"),
        updated_at=_dt(item["updated_at"], "team.updated_at"),
        members=MappingProxyType(members), last_transaction_id=str(item["last_transaction_id"]),
    )


def _task(value: object) -> SharedTaskRecord:
    keys = {item.name for item in fields(SharedTaskRecord)}
    item = _strict(value, keys, label="task")
    logs: list[TaskWorkEntry] = []
    for raw in _list(item["work_log"], "task.work_log"):
        entry = _strict(raw, {"timestamp", "actor", "summary"}, label="task work log")
        logs.append(TaskWorkEntry(_dt(entry["timestamp"], "work_log.timestamp"), _actor(entry["actor"]), str(entry["summary"])))
    return SharedTaskRecord(
        task_id=str(item["task_id"]), revision=_int(item["revision"], "task.revision"),
        title=str(item["title"]), description=str(item["description"]), status=_literal(item["status"], {"pending", "dependency_blocked", "waiting_approval", "ready", "running", "blocked", "completed", "cancelled"}, "task.status"),  # type: ignore[arg-type]
        assignee_id=item["assignee_id"] if isinstance(item["assignee_id"], str) else None,
        dependency_ids=tuple(str(part) for part in _list(item["dependency_ids"], "dependency_ids")),
        creator=_actor(item["creator"]), work_log=tuple(logs),
        plan_version=item["plan_version"] if isinstance(item["plan_version"], int) else None,
        result_commit=item["result_commit"] if isinstance(item["result_commit"], str) else None,
        integrated_by=item["integrated_by"] if isinstance(item["integrated_by"], str) else None,
        deleted_at=_dt(item["deleted_at"], "task.deleted_at") if item["deleted_at"] is not None else None,
        created_at=_dt(item["created_at"], "task.created_at"), updated_at=_dt(item["updated_at"], "task.updated_at"),
    )


def _approval(value: object) -> ApprovalRecord:
    keys = {item.name for item in fields(ApprovalRecord)}
    item = _strict(value, keys, label="approval")
    return ApprovalRecord(
        task_id=str(item["task_id"]), member_id=str(item["member_id"]),
        plan_version=_int(item["plan_version"], "approval.plan_version"),
        plan_fingerprint=str(item["plan_fingerprint"]), plan_body=str(item["plan_body"]),
        status=_literal(item["status"], {"pending", "approved", "rejected", "superseded"}, "approval.status"),  # type: ignore[arg-type]
        requested_at=_dt(item["requested_at"], "approval.requested_at"),
        decided_at=_dt(item["decided_at"], "approval.decided_at") if item["decided_at"] is not None else None,
        decided_by=_actor(item["decided_by"]) if item["decided_by"] is not None else None,
        reason=str(item["reason"]),
        decision_message_id=item["decision_message_id"] if isinstance(item["decision_message_id"], str) else None,
    )


def _verification(value: object) -> VerificationResult:
    keys = {item.name for item in fields(VerificationResult)}
    item = _strict(value, keys, label="verification result")
    return VerificationResult(
        str(item["command_id"]), _int(item["returncode"], "verification.returncode"),
        str(item["summary"]), _dt(item["started_at"], "verification.started_at"),
        _dt(item["finished_at"], "verification.finished_at"),
    )


def _integration(value: object) -> IntegrationRecord:
    keys = {item.name for item in fields(IntegrationRecord)}
    item = _strict(value, keys, label="integration")
    raw_commits = item["member_commits"]
    if not isinstance(raw_commits, dict):
        raise TeamError("invalid_schema", "integration.member_commits 必须是对象。")
    return IntegrationRecord(
        integration_id=str(item["integration_id"]), revision=_int(item["revision"], "integration.revision"),
        status=_literal(item["status"], {"preparing", "merging", "validating", "ready_to_advance", "advancing", "completed", "conflicted", "failed", "aborted"}, "integration.status"), lead_branch_ref=str(item["lead_branch_ref"]),  # type: ignore[arg-type]
        base_commit=str(item["base_commit"]), task_ids=tuple(str(part) for part in _list(item["task_ids"], "task_ids")),
        member_commits=MappingProxyType({str(key): tuple(str(part) for part in _list(raw, "member commits")) for key, raw in raw_commits.items()}),
        integration_branch_ref=str(item["integration_branch_ref"]), integration_worktree=str(item["integration_worktree"]),
        merged_commit=item["merged_commit"] if isinstance(item["merged_commit"], str) else None,
        verification_results=tuple(_verification(raw) for raw in _list(item["verification_results"], "verification_results")),
        conflict_paths=tuple(str(part) for part in _list(item["conflict_paths"], "conflict_paths")),
        failure_reason=str(item["failure_reason"]), created_at=_dt(item["created_at"], "integration.created_at"),
        finished_at=_dt(item["finished_at"], "integration.finished_at") if item["finished_at"] is not None else None,
    )


def _schema(value: object) -> int:
    number = _int(value, "schema_version")
    if number != SCHEMA_VERSION:
        raise TeamError("unsupported_schema", f"不支持的团队 schema 版本：{number}")
    return number


def _int(value: object, label: str) -> int:
    if type(value) is not int:
        raise TeamError("invalid_schema", f"{label} 必须是整数。")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise TeamError("invalid_schema", f"{label} 必须是布尔值。")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TeamError("invalid_schema", f"{label} 必须是列表。")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    items = _list(value, label)
    if not all(isinstance(item, str) for item in items):
        raise TeamError("invalid_schema", f"{label} 必须只包含字符串。")
    return tuple(items)


def _literal(value: object, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise TeamError("invalid_schema", f"{label} 包含未知状态值。")
    return value


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TeamError("invalid_schema", f"{label} 必须是非空字符串。")
    return value


class FileTeamStore:
    def __init__(self, *, user_root: Path | None = None, config: TeamConfig | None = None) -> None:
        self.user_root = user_root
        self.config = config or TeamConfig()

    def create(self, request: TeamCreateRequest | TeamSnapshot) -> TeamSnapshot:
        if isinstance(request, TeamSnapshot):
            snapshot = request
        else:
            now = utc_now()
            snapshot = TeamSnapshot(
                schema_version=SCHEMA_VERSION, revision=1, name=validate_team_name(request.name),
                status="active", lead_name="lead", repository_id=request.repository_id,
                workspace_root=request.workspace_root, lead_branch_ref=request.lead_branch_ref,
                created_at=now, updated_at=now,
            )
        root = team_dir(snapshot.name, self.user_root)
        if root.exists():
            raise TeamError("team_exists", f"小组 `{snapshot.name}` 已存在。")
        root.parent.mkdir(parents=True, exist_ok=True)
        root.mkdir(mode=0o700)
        try:
            for child in ("mailboxes", "contexts", ".locks", ".transactions"):
                safe_child(root, child, allow_missing=True).mkdir(mode=0o700)
            self._write_json(root / "team.json", _json_value(snapshot))
            for name in _SNAPSHOT_FILES[1:]:
                self._write_json(root / name, {"schema_version": SCHEMA_VERSION, "revision": snapshot.revision, "items": {}})
            self._append_audit_unlocked(root, "create", "committed", "team", snapshot.name)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return snapshot

    def load(self, team_name: str) -> TeamAggregate:
        name = validate_team_name(team_name)
        root = team_dir(name, self.user_root)
        with FileLock(lock_path(name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            self.recover_transactions(name, already_locked=True)
            aggregate = self._load_unlocked(root)
        self._validate_aggregate(aggregate)
        return aggregate

    def transact(
        self,
        team_name: str,
        expected_revisions: RevisionSet,
        mutation: Callable[[TeamAggregate], TeamAggregate],
    ) -> TeamAggregate:
        name = validate_team_name(team_name)
        root = team_dir(name, self.user_root)
        with FileLock(lock_path(name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            self.recover_transactions(name, already_locked=True)
            before = self._load_unlocked(root)
            if expected_revisions.team is not None and before.team.revision != expected_revisions.team:
                raise TeamError("revision_conflict", "团队 revision 已变化，请刷新后重试。")
            after = mutation(before)
            self._validate_aggregate(after)
            transaction_id = f"tx_{secrets.token_hex(8)}"
            team = after.team
            if team.revision <= before.team.revision:
                team = replace(team, revision=before.team.revision + 1)
            team = replace(team, updated_at=utc_now(), last_transaction_id=transaction_id)
            after = replace(after, team=team)
            self._append_audit_unlocked(root, transaction_id, "intent", "transaction", transaction_id)
            try:
                self._commit_transaction(root, transaction_id, before, after)
            except Exception:
                try:
                    self._append_audit_unlocked(root, transaction_id, "failed", "transaction", transaction_id)
                finally:
                    raise
            self._append_audit_unlocked(root, transaction_id, "committed", "transaction", transaction_id)
            return after

    def append_mailbox(self, team_name: str, recipient: str, record: MailboxRecord) -> int:
        return self.append_mailbox_record(team_name, recipient, record).sequence

    def append_mailbox_record(
        self, team_name: str, recipient: str, record: MailboxRecord
    ) -> MailboxRecord:
        path = mailbox_path(team_name, recipient, self.user_root)
        with FileLock(lock_path(team_name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            records = tuple(self._mailbox_record(item) for item in self._read_jsonl(path, "邮箱"))
            if isinstance(record, MailboxMessage):
                existing = next((
                    item for item in records
                    if isinstance(item, MailboxMessage) and item.idempotency_key == record.idempotency_key
                ), None)
                if existing is not None:
                    return existing
            else:
                existing_ack = next((
                    item for item in records
                    if isinstance(item, MailboxAck) and item.message_id == record.message_id
                ), None)
                if existing_ack is not None:
                    return existing_ack
            assigned = replace(
                record, sequence=max((item.sequence for item in records), default=0) + 1
            )
            self._append_jsonl_unlocked(path, assigned, limit=self.config.max_mailbox_bytes)
            self._append_audit_unlocked(
                team_dir(team_name, self.user_root),
                getattr(assigned, "message_id", "mailbox"),
                "committed",
                "mailbox_record",
                getattr(assigned, "message_id", "mailbox"),
            )
            return assigned

    def read_mailbox(self, team_name: str, recipient: str) -> tuple[MailboxRecord, ...]:
        path = mailbox_path(team_name, recipient, self.user_root)
        with FileLock(lock_path(team_name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            return tuple(self._mailbox_record(item) for item in self._read_jsonl(path, "邮箱"))

    def append_context(
        self, team_name: str, member: str, records: Sequence[MemberContextRecord]
    ) -> int:
        path = context_path(team_name, member, self.user_root)
        if not records:
            return 0
        with FileLock(lock_path(team_name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            existing = tuple(self._context_record(item) for item in self._read_jsonl(path, "成员上下文"))
            expected = existing[-1].sequence + 1 if existing else 1
            if any(record.sequence != expected + index for index, record in enumerate(records)):
                raise TeamError("context_sequence_conflict", "成员上下文 sequence 不连续。")
            self._append_jsonl_batch_unlocked(path, records, limit=self.config.max_context_bytes)
            return records[-1].sequence

    def read_context(self, team_name: str, member: str) -> tuple[MemberContextRecord, ...]:
        path = context_path(team_name, member, self.user_root)
        with FileLock(lock_path(team_name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            records = tuple(self._context_record(item) for item in self._read_jsonl(path, "成员上下文"))
        expected = 1
        valid: list[MemberContextRecord] = []
        pending_calls: set[str] = set()
        batch_start = 0
        for record in records:
            if record.sequence != expected:
                break
            expected += 1
            message = record.message
            if message.role == "assistant" and message.tool_calls:
                batch_start = len(valid)
                pending_calls = {call.id for call in message.tool_calls}
            elif message.role == "tool" and pending_calls:
                pending_calls.discard(message.tool_call_id)
            elif pending_calls:
                break
            valid.append(record)
        if pending_calls:
            valid = valid[:batch_start]
        return tuple(valid)

    def archive(self, team_name: str, expected_revision: int) -> Path:
        from .paths import archive_root

        name = validate_team_name(team_name)
        source = team_dir(name, self.user_root)
        with FileLock(lock_path(name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            aggregate = self._load_unlocked(source)
            if aggregate.team.revision != expected_revision:
                raise TeamError("revision_conflict", "团队 revision 已变化，请刷新后重试。")
            suffix = utc_now().strftime("%Y%m%d-%H%M%S")
            destination = archive_root(self.user_root) / f"{name}-{suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise TeamError("archive_exists", "归档目标已存在。")
            os.replace(source, destination)
            self._fsync_directory(destination.parent)
            return destination

    def recover_transactions(self, team_name: str, *, already_locked: bool = False) -> None:
        name = validate_team_name(team_name)
        root = team_dir(name, self.user_root)
        if not already_locked:
            with FileLock(lock_path(name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
                self.recover_transactions(name, already_locked=True)
            return
        transactions = safe_child(root, ".transactions", allow_missing=True)
        if not transactions.exists():
            return
        for directory in sorted(item for item in transactions.iterdir() if item.is_dir()):
            manifest_path = directory / "manifest.json"
            committed = directory / "committed"
            if committed.exists():
                shutil.rmtree(directory)
                continue
            manifest = _loads(self._read_text(manifest_path, "事务 manifest"), label="事务 manifest")
            manifest_obj = _strict(manifest, {"schema_version", "transaction_id", "files"}, label="事务 manifest")
            _schema(manifest_obj["schema_version"])
            files = manifest_obj["files"]
            if not isinstance(files, dict):
                raise TeamError("invalid_transaction", "事务文件表无效。")
            for filename, detail in files.items():
                if filename not in _SNAPSHOT_FILES:
                    raise TeamError("invalid_transaction", "事务包含非法目标文件。")
                entry = _strict(detail, {"before_hash", "after_hash"}, label="事务文件")
                target = root / filename
                after_file = directory / f"after-{filename}"
                current_hash = self._hash_file(target)
                before_hash, after_hash = str(entry["before_hash"]), str(entry["after_hash"])
                if current_hash == after_hash:
                    continue
                if current_hash != before_hash or self._hash_file(after_file) != after_hash:
                    raise TeamError("transaction_diverged", "事务恢复发现第三种文件内容，已停止自动恢复。")
                self._replace_from_staged(after_file, target)
            self._write_bytes(committed, b"committed\n")
            shutil.rmtree(directory)

    def _commit_transaction(
        self, root: Path, transaction_id: str, before: TeamAggregate, after: TeamAggregate
    ) -> None:
        tx_root = root / ".transactions" / transaction_id
        tx_root.mkdir(parents=True, mode=0o700)
        documents = self._documents(after)
        manifest_files: dict[str, dict[str, str]] = {}
        for filename, value in documents.items():
            target = root / filename
            staged = tx_root / f"after-{filename}"
            self._write_json(staged, value)
            manifest_files[filename] = {
                "before_hash": self._hash_file(target),
                "after_hash": self._hash_file(staged),
            }
        self._write_json(tx_root / "manifest.json", {
            "schema_version": SCHEMA_VERSION,
            "transaction_id": transaction_id,
            "files": manifest_files,
        })
        self._write_bytes(tx_root / "intent", b"intent\n")
        for filename in _SNAPSHOT_FILES:
            self._replace_from_staged(tx_root / f"after-{filename}", root / filename)
        self._write_bytes(tx_root / "committed", b"committed\n")
        shutil.rmtree(tx_root)

    def _documents(self, aggregate: TeamAggregate) -> dict[str, object]:
        return {
            "team.json": _json_value(aggregate.team),
            "tasks.json": {"schema_version": SCHEMA_VERSION, "revision": aggregate.team.revision, "items": _json_value(aggregate.tasks)},
            "approvals.json": {"schema_version": SCHEMA_VERSION, "revision": aggregate.team.revision, "items": _json_value(aggregate.approvals)},
            "integrations.json": {"schema_version": SCHEMA_VERSION, "revision": aggregate.team.revision, "items": _json_value(aggregate.integrations)},
        }

    def _load_unlocked(self, root: Path) -> TeamAggregate:
        if not root.is_dir() or root.is_symlink():
            raise TeamError("team_not_found", f"小组不存在：{root.name}")
        team = _team(self._read_json(root / "team.json", "team.json"))
        tasks_revision, tasks = self._load_items(root / "tasks.json", _task, "tasks.json")
        approvals_revision, approvals = self._load_items(root / "approvals.json", _approval, "approvals.json")
        integrations_revision, integrations = self._load_items(root / "integrations.json", _integration, "integrations.json")
        if {tasks_revision, approvals_revision, integrations_revision} != {team.revision}:
            raise TeamError("aggregate_revision_mismatch", "团队聚合文件 revision 不一致。")
        return TeamAggregate(
            team,
            MappingProxyType(tasks),
            MappingProxyType(approvals),
            MappingProxyType(integrations),
        )

    def _load_items(self, path: Path, parser: Callable[[object], Any], label: str) -> tuple[int, dict[str, Any]]:
        raw = _strict(self._read_json(path, label), {"schema_version", "revision", "items"}, label=label)
        _schema(raw["schema_version"])
        revision = _int(raw["revision"], f"{label}.revision")
        items = raw["items"]
        if not isinstance(items, dict):
            raise TeamError("invalid_schema", f"{label}.items 必须是对象。")
        return revision, {str(key): parser(value) for key, value in items.items()}

    def _validate_aggregate(self, aggregate: TeamAggregate) -> None:
        if aggregate.team.schema_version != SCHEMA_VERSION or aggregate.team.lead_name != "lead":
            raise TeamError("invalid_aggregate", "团队快照版本或负责人无效。")
        if len(aggregate.team.members) > self.config.max_members:
            raise TeamError("member_limit", "团队成员数量达到配置上限。")
        if len(aggregate.tasks) > self.config.max_tasks:
            raise TeamError("task_limit", "共享任务数量达到配置上限。")
        members = set(aggregate.team.members)
        tasks = set(aggregate.tasks)
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise TeamError("dependency_cycle", "持久化任务依赖形成循环。")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in aggregate.tasks[task_id].dependency_ids:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)
        for key, task in aggregate.tasks.items():
            if key != task.task_id:
                raise TeamError("invalid_cross_reference", "任务映射键与 task_id 不一致。")
            if task.assignee_id is not None and task.assignee_id not in members:
                raise TeamError("invalid_cross_reference", "任务负责人不在当前小组。")
            if any(dependency not in tasks for dependency in task.dependency_ids):
                raise TeamError("invalid_cross_reference", "任务依赖不存在。")
            visit(task.task_id)
        for member_id, member in aggregate.team.members.items():
            if member_id != member.member_id:
                raise TeamError("invalid_cross_reference", "成员映射键与 member_id 不一致。")
            if member.current_task_id is not None and member.current_task_id not in tasks:
                raise TeamError("invalid_cross_reference", "成员当前任务不存在。")
        for key, approval in aggregate.approvals.items():
            expected = f"{approval.member_id}:{approval.task_id}:{approval.plan_version}"
            if key != expected or approval.member_id not in members or approval.task_id not in tasks:
                raise TeamError("invalid_cross_reference", "审批记录交叉引用无效。")
        for key, integration in aggregate.integrations.items():
            if key != integration.integration_id or any(task_id not in tasks for task_id in integration.task_ids):
                raise TeamError("invalid_cross_reference", "集成记录交叉引用无效。")

    def _append_jsonl(self, team_name: str, path: Path, record: object, *, limit: int) -> int:
        with FileLock(lock_path(team_name, user_root=self.user_root), timeout_seconds=self.config.lock_timeout_seconds):
            self._append_jsonl_unlocked(path, record, limit=limit)
            return getattr(record, "sequence", 0)

    def _append_jsonl_unlocked(self, path: Path, record: object, *, limit: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        line = json.dumps(_json_value(record), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        current_size = path.stat().st_size if path.exists() else 0
        if current_size + len(line) > limit:
            raise TeamError("storage_limit", f"{path.name} 已达到配置的存储上限。")
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, line)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _append_jsonl_batch_unlocked(
        self, path: Path, records: Sequence[object], *, limit: int
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = b"".join(
            json.dumps(_json_value(record), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
            for record in records
        )
        current_size = path.stat().st_size if path.exists() else 0
        if current_size + len(raw) > limit:
            raise TeamError("storage_limit", f"{path.name} 已达到配置的存储上限。")
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            offset = 0
            while offset < len(raw):
                offset += os.write(descriptor, raw[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _mailbox_record(self, value: object) -> MailboxRecord:
        if not isinstance(value, dict):
            raise TeamError("invalid_schema", "邮箱记录必须是对象。")
        record_type = value.get("record_type")
        if record_type == "message":
            item = _strict(value, {item.name for item in fields(MailboxMessage)}, label="mailbox message")
            if item["read"] is not False:
                raise TeamError("invalid_schema", "原始 mailbox message 的 read 必须为 false。")
            from .protocols import protocol_dict
            protocol = protocol_dict(item["protocol"] if isinstance(item["protocol"], dict) else None)
            return MailboxMessage(
                _schema(item["schema_version"]), "message", _int(item["sequence"], "message.sequence"),
                str(item["message_id"]), _actor(item["sender"]), str(item["body"]),
                _dt(item["timestamp"], "message.timestamp"), False, str(item["summary"]),
                protocol,
                str(item["idempotency_key"]),
            )
        if record_type == "ack":
            item = _strict(value, {item.name for item in fields(MailboxAck)}, label="mailbox ack")
            return MailboxAck(
                _schema(item["schema_version"]), "ack", _int(item["sequence"], "ack.sequence"),
                str(item["message_id"]), _actor(item["reader"]), _dt(item["timestamp"], "ack.timestamp"),
            )
        raise TeamError("invalid_schema", "未知邮箱记录类型。")

    def _context_record(self, value: object) -> MemberContextRecord:
        item = _strict(value, {item.name for item in fields(MemberContextRecord)}, label="member context")
        message_raw = _strict(
            item["message"], {"role", "content", "tool_calls", "tool_call_id"}, label="context message"
        )
        calls = []
        for raw in _list(message_raw["tool_calls"], "message.tool_calls"):
            call = _strict(raw, {"id", "name", "arguments"}, label="tool call")
            arguments = call["arguments"]
            if not isinstance(arguments, dict):
                raise TeamError("invalid_schema", "tool call arguments 必须是对象。")
            calls.append(ToolCall(str(call["id"]), str(call["name"]), arguments))
        message = Message(
            _literal(message_raw["role"], {"user", "assistant", "tool"}, "message.role"),
            str(message_raw["content"]), tuple(calls), str(message_raw["tool_call_id"])  # type: ignore[arg-type]
        )
        return MemberContextRecord(
            _schema(item["schema_version"]), _int(item["sequence"], "context.sequence"),
            _dt(item["timestamp"], "context.timestamp"), message,
            tuple(str(part) for part in _list(item["source_message_ids"], "source_message_ids")),
        )

    def _read_jsonl(self, path: Path, label: str) -> list[object]:
        if not path.exists():
            return []
        raw = self._read_text(path, label)
        result: list[object] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line.strip():
                continue
            result.append(_loads(line, label=f"{label} 第 {number} 行"))
        return result

    def _read_json(self, path: Path, label: str) -> object:
        return _loads(self._read_text(path, label), label=label)

    def _read_text(self, path: Path, label: str) -> str:
        if path.is_symlink():
            raise TeamError("symlink_file", f"{label} 不能是符号链接。")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise TeamError("read_failed", f"无法读取 {label}。") from exc

    def _write_json(self, path: Path, value: object) -> None:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
        self._atomic_write(path, raw)

    def _atomic_write(self, path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        self._write_bytes(temporary, raw)
        os.replace(temporary, path)
        self._fsync_directory(path.parent)

    def _write_bytes(self, path: Path, raw: bytes) -> None:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            os.write(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _replace_from_staged(self, staged: Path, target: Path) -> None:
        raw = staged.read_bytes()
        self._atomic_write(target, raw)

    def _append_audit_unlocked(
        self,
        root: Path,
        transaction_id: str,
        outcome: str,
        object_type: str,
        object_id: str,
    ) -> None:
        event = AuditEvent(
            SCHEMA_VERSION,
            f"audit_{secrets.token_hex(8)}",
            transaction_id,
            utc_now(),
            ActorRef("system", "system"),
            "store_transaction",
            object_type,
            object_id,
            outcome,  # type: ignore[arg-type]
            "",
            f"{object_type} {outcome}",
        )
        path = root / "audit.jsonl"
        self._append_jsonl_unlocked(path, event, limit=max(self.config.max_mailbox_bytes, 1024**2))

    @staticmethod
    def _hash_file(path: Path) -> str:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return "missing"
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
