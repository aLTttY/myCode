from __future__ import annotations

import re
import shlex
import fnmatch
from pathlib import Path

from .models import PermissionValidationError


SHELL_OPERATORS = {"|", "||", "&", "&&", ";", "(", ")"}
REDIRECT_OPERATORS = {">", ">>", "<", "<<"}
URL_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def resolve_workspace_path(
    workspace_root: Path,
    value: str,
    *,
    allow_absolute: bool = False,
    excluded_roots: tuple[Path, ...] = (),
) -> tuple[Path, str]:
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
    for excluded in excluded_roots:
        try:
            resolved.relative_to(excluded.resolve(strict=False))
        except ValueError:
            continue
        raise PermissionValidationError(
            "excluded_workspace",
            "路径位于当前任务排除的受管工作区。",
            value,
        )
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


def validate_command_paths(
    command: str,
    workspace_root: Path,
    excluded_roots: tuple[Path, ...] = (),
) -> None:
    tokens = _shell_tokens(command)
    destructive = _is_destructive_command(tokens)
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
        if destructive and _destructive_pattern_overlaps(
            token,
            workspace_root,
            excluded_roots,
        ):
            raise PermissionValidationError(
                "excluded_workspace_ancestor",
                "破坏性命令通配目标可能包含受管 Worktree，已拒绝。",
                token,
            )
        path_value = _path_value(token, workspace_root, redirected)
        redirected = False
        if path_value is not None:
            resolved, _ = resolve_workspace_path(
                workspace_root,
                path_value,
                allow_absolute=True,
                excluded_roots=excluded_roots,
            )
            if destructive:
                for excluded in excluded_roots:
                    try:
                        excluded.resolve(strict=False).relative_to(resolved)
                    except ValueError:
                        continue
                    raise PermissionValidationError(
                        "excluded_workspace_ancestor",
                        "破坏性命令目标包含受管 Worktree，已拒绝。",
                        path_value,
                    )
    if _is_destructive_git_clean(tokens) and excluded_roots:
        raise PermissionValidationError(
            "excluded_workspace_ancestor",
            "破坏性 git clean 可能删除受管 Worktree，已拒绝。",
            command,
        )


def _is_destructive_command(tokens: list[str]) -> bool:
    lowered = [token.lower() for token in tokens]
    return (
        any(token in {"rm", "rmdir"} for token in lowered)
        or ("find" in lowered and "-delete" in lowered)
        or _is_destructive_git_clean(tokens)
    )


def _is_destructive_git_clean(tokens: list[str]) -> bool:
    lowered = [token.lower() for token in tokens]
    for index in range(len(lowered) - 1):
        if lowered[index:index + 2] == ["git", "clean"]:
            flags = lowered[index + 2:]
            return any("f" in item.lstrip("-") for item in flags) and any(
                "x" in item.lstrip("-") for item in flags
            )
    return False


def _destructive_pattern_overlaps(
    token: str,
    workspace_root: Path,
    excluded_roots: tuple[Path, ...],
) -> bool:
    if not excluded_roots or not any(character in token for character in "*?["):
        return False
    pattern = token
    if pattern.startswith("-") and "=" in pattern:
        pattern = pattern.split("=", 1)[1]
    if Path(pattern).is_absolute() or pattern.startswith("~") or "$" in pattern:
        return True
    normalized = pattern.removeprefix("./").rstrip("/")
    root = workspace_root.resolve(strict=False)
    for excluded in excluded_roots:
        try:
            relative = excluded.resolve(strict=False).relative_to(root)
        except ValueError:
            return True
        parts = relative.as_posix().split("/")
        prefixes = ("/".join(parts[:index]) for index in range(1, len(parts) + 1))
        if any(_shell_glob_matches(normalized, prefix) for prefix in prefixes):
            return True
    return False


def _shell_glob_matches(pattern: str, value: str) -> bool:
    pattern_parts = pattern.split("/")
    value_parts = value.split("/")
    for pattern_part, value_part in zip(pattern_parts, value_parts):
        if value_part.startswith(".") and not pattern_part.startswith("."):
            return False
    return fnmatch.fnmatchcase(value, pattern)
