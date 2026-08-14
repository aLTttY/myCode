from __future__ import annotations

import os
import re
from pathlib import Path

from .models import TeamError


SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TASK_ID = re.compile(r"^team_task_[a-f0-9]{16}$")
MESSAGE_ID = re.compile(r"^team_msg_[a-f0-9]{16}$")
INTEGRATION_ID = re.compile(r"^team_int_[a-f0-9]{16}$")
MEMBER_ID = re.compile(r"^team_member_[a-f0-9]{16}$")
RESERVED_NAMES = {"lead", "system", ".locks", ".transactions", "mailboxes", "contexts"}


def teams_root(user_root: Path | None = None) -> Path:
    base = (user_root if user_root is not None else Path.home()).expanduser()
    return base / ".mycode" / "teams"


def archive_root(user_root: Path | None = None) -> Path:
    base = (user_root if user_root is not None else Path.home()).expanduser()
    return base / ".mycode" / "teams-archive"


def validate_team_name(name: str) -> str:
    if not isinstance(name, str) or SAFE_NAME.fullmatch(name) is None or name in RESERVED_NAMES:
        raise TeamError("invalid_team_name", "小组名只能使用小写字母、数字、下划线或连字符，长度 1–64。")
    return name


def validate_member_name(name: str) -> str:
    if not isinstance(name, str) or SAFE_NAME.fullmatch(name) is None or name in RESERVED_NAMES:
        raise TeamError("invalid_member_name", "成员名非法或使用了保留名称。")
    return name


def _validate_id(value: str, pattern: re.Pattern[str], kind: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise TeamError(f"invalid_{kind}_id", f"{kind} ID 非法。")
    return value


def validate_task_id(value: str) -> str:
    return _validate_id(value, TASK_ID, "task")


def validate_message_id(value: str) -> str:
    return _validate_id(value, MESSAGE_ID, "message")


def validate_integration_id(value: str) -> str:
    return _validate_id(value, INTEGRATION_ID, "integration")


def validate_member_id(value: str) -> str:
    return _validate_id(value, MEMBER_ID, "member")


def team_dir(name: str, user_root: Path | None = None) -> Path:
    return safe_child(teams_root(user_root), validate_team_name(name), allow_missing=True)


def archived_team_dir(name: str, suffix: str, user_root: Path | None = None) -> Path:
    validate_team_name(name)
    if SAFE_NAME.fullmatch(suffix) is None:
        raise TeamError("invalid_archive_suffix", "归档后缀非法。")
    return safe_child(archive_root(user_root), f"{name}-{suffix}", allow_missing=True)


def mailbox_path(name: str, member_name: str, user_root: Path | None = None) -> Path:
    root = safe_child(team_dir(name, user_root), "mailboxes", allow_missing=True)
    mailbox_name = "lead" if member_name == "lead" else validate_member_name(member_name)
    return safe_child(root, f"{mailbox_name}.jsonl", allow_missing=True)


def context_path(name: str, member_name: str, user_root: Path | None = None) -> Path:
    root = safe_child(team_dir(name, user_root), "contexts", allow_missing=True)
    return safe_child(root, f"{validate_member_name(member_name)}.jsonl", allow_missing=True)


def lock_path(name: str, member_name: str | None = None, user_root: Path | None = None) -> Path:
    root = safe_child(team_dir(name, user_root), ".locks", allow_missing=True)
    filename = "team.lock" if member_name is None else f"member-{validate_member_name(member_name)}.lock"
    return safe_child(root, filename, allow_missing=True)


def safe_child(root: Path, *parts: str, allow_missing: bool) -> Path:
    if not parts or any(
        not isinstance(part, str)
        or not part
        or "\\" in part
        or Path(part).is_absolute()
        or any(segment in {"", ".", ".."} for segment in part.split("/"))
        for part in parts
    ):
        raise TeamError("invalid_path", "团队路径包含非法片段。")
    lexical_root = Path(os.path.abspath(root))
    candidate = lexical_root.joinpath(*parts)
    try:
        candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise TeamError("path_escape", "团队路径逃离专用根目录。") from exc
    cursor = lexical_root
    if cursor.exists() and cursor.is_symlink():
        raise TeamError("symlink_escape", "团队路径不能经过符号链接。")
    for part in candidate.relative_to(lexical_root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise TeamError("symlink_escape", "团队路径不能经过符号链接。")
        if not cursor.exists():
            break
    if not allow_missing and not candidate.exists():
        raise TeamError("missing_path", "团队路径不存在。")
    return candidate
