from __future__ import annotations

import re
import shlex
from pathlib import Path

from .models import PermissionValidationError


SHELL_OPERATORS = {"|", "||", "&", "&&", ";", "(", ")"}
REDIRECT_OPERATORS = {">", ">>", "<", "<<"}
URL_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def resolve_workspace_path(workspace_root: Path, value: str, *, allow_absolute: bool = False) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise PermissionValidationError("invalid_target", "路径必须是非空字符串。")
    root = workspace_root.resolve()
    requested = Path(value).expanduser()
    if requested.is_absolute() and not allow_absolute:
        raise PermissionValidationError("sandbox_escape", "绝对路径不允许用于文件工具。", value)
    candidate = requested if requested.is_absolute() else root / requested
    try:
        resolved = candidate.resolve()
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PermissionValidationError(
            "sandbox_escape",
            "路径不在项目目录内；请改用项目内相对路径或专用工具。",
            value,
        ) from exc
    return resolved, relative.as_posix() or "."


def validate_pattern_target(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise PermissionValidationError("invalid_target", "模式必须是非空字符串。")
    normalized = value.replace("\\", "/")
    if normalized.startswith(("/", "~/")) or any(part == ".." for part in normalized.split("/")):
        raise PermissionValidationError(
            "sandbox_escape",
            "搜索模式不能指向项目目录外。",
            value,
        )
    return normalized


def _shell_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError as exc:
        raise PermissionValidationError("invalid_target", f"命令无法解析：{exc}", command) from exc


def _path_value(token: str, workspace_root: Path, redirected: bool) -> str | None:
    value = token
    if token.startswith("-") and "=" in token:
        value = token.split("=", 1)[1]
    if not value or URL_PATTERN.match(value):
        return None
    if "$" in value and ("/" in value or redirected):
        raise PermissionValidationError(
            "sandbox_escape",
            "命令中的显式路径包含无法安全解析的环境变量。",
            value,
        )
    if redirected or value.startswith(("/", "./", "../", "~/")) or "/" in value:
        return value
    if (workspace_root / value).exists():
        return value
    return None


def validate_command_paths(command: str, workspace_root: Path) -> None:
    tokens = _shell_tokens(command)
    expect_command = True
    redirected = False
    for token in tokens:
        if token in SHELL_OPERATORS:
            expect_command = True
            redirected = False
            continue
        if token in REDIRECT_OPERATORS:
            redirected = True
            continue
        if expect_command:
            expect_command = False
            redirected = False
            continue
        path_value = _path_value(token, workspace_root, redirected)
        redirected = False
        if path_value is not None:
            resolve_workspace_path(workspace_root, path_value, allow_absolute=True)
