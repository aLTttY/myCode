from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from mycode.permissions.models import PermissionValidationError
from mycode.permissions.sandbox import resolve_workspace_path
from mycode.tools.base import execution_result, optional_bool, require_str, result_error, result_ok, truncate_text
from mycode.types import ToolContext, ToolError, ToolExecutionResult, ToolResult, ToolSpec


SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
MAX_MATCHES = 100


def _inside_workspace(path: Path, workspace_root: Path) -> bool:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _iter_files(root: Path, workspace_root: Path) -> Iterable[Path]:
    if root.is_file() and _inside_workspace(root, workspace_root):
        yield root
        return
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and _inside_workspace(path, workspace_root):
            yield path


def _is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:1024]
    except OSError:
        return True
    return b"\0" in chunk


class FindFilesTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="find_files",
            description="Find files in the workspace by filename or relative path pattern.",
            parameters={
                "type": "object",
                "properties": {"pattern": {"type": "string", "description": "Glob-style pattern."}},
                "required": ["pattern"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult | ToolExecutionResult:
        try:
            pattern = require_str(arguments, "pattern")
            matches: list[str] = []
            root = context.workspace_root.resolve()
            for path in _iter_files(root, root):
                relative = path.relative_to(root).as_posix()
                if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern):
                    matches.append(relative)
                    if len(matches) >= MAX_MATCHES:
                        break
            full_matches = list(matches)
            output, truncated = truncate_text("\n".join(full_matches), context.max_output_chars)
            if truncated:
                matches = output.splitlines()
            display = result_ok("文件搜索完成。", matches=matches, count=len(matches), truncated=truncated)
            if not truncated:
                return execution_result(display)
            complete = result_ok("文件搜索完成。", matches=full_matches, count=len(full_matches), truncated=False)
            return execution_result(display, complete)
        except ToolError as exc:
            return result_error(exc.user_message)


class SearchCodeTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_code",
            description="Search workspace text files by literal text or regular expression.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or regex to search for."},
                    "regex": {"type": "boolean", "description": "Whether query is a regular expression."},
                    "path": {
                        "type": "string",
                        "description": "Optional workspace-relative file or directory scope. Defaults to `.`.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        try:
            query = require_str(arguments, "query")
            use_regex = optional_bool(arguments, "regex", False)
            pattern = re.compile(query) if use_regex else None
        except re.error as exc:
            return result_error(f"正则表达式无效：{exc}")
        except ToolError as exc:
            return result_error(exc.user_message)

        try:
            scope = arguments.get("path", ".")
            if not isinstance(scope, str) or not scope:
                raise ToolError("参数 `path` 必须是非空字符串。")
            root, _ = resolve_workspace_path(context.workspace_root, scope)
            if not root.exists():
                return result_error("搜索范围不存在。", path=str(root))
        except ToolError as exc:
            return result_error(exc.user_message)
        except PermissionValidationError as exc:
            return result_error(exc.message)
        matches: list[dict[str, object]] = []
        workspace_root = context.workspace_root.resolve()
        for path in _iter_files(root, workspace_root):
            if _is_binary(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(lines, start=1):
                found = pattern.search(line) is not None if pattern else query in line
                if found:
                    matches.append(
                        {
                            "path": path.relative_to(workspace_root).as_posix(),
                            "line": line_number,
                            "text": line.strip(),
                        }
                    )
                    if len(matches) >= MAX_MATCHES:
                        return result_ok("代码搜索完成。", matches=matches, count=len(matches), truncated=True)
        return result_ok("代码搜索完成。", matches=matches, count=len(matches), truncated=False)
