from __future__ import annotations

from collections.abc import Mapping

from mycode.tools.base import execution_result, require_str, require_string, resolve_workspace_path, result_error, result_ok, truncate_text
from mycode.types import ToolContext, ToolError, ToolExecutionResult, ToolResult, ToolSpec


class ReadFileTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_file",
            description="Read a UTF-8 text file inside the workspace.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path. Absolute paths are invalid; use values like `test.md`.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult | ToolExecutionResult:
        try:
            path = resolve_workspace_path(context.workspace_root, require_str(arguments, "path"))
            if not path.exists():
                return result_error("文件不存在。", path=str(path))
            if not path.is_file():
                return result_error("目标路径不是文件。", path=str(path))
            full_content = path.read_text(encoding="utf-8")
            content, truncated = truncate_text(full_content, context.max_output_chars)
            display = result_ok("文件读取成功。", path=str(path), content=content, size=path.stat().st_size, truncated=truncated)
            if not truncated:
                return execution_result(display)
            complete = result_ok("文件读取成功。", path=str(path), content=full_content, size=path.stat().st_size, truncated=False)
            return execution_result(display, complete)
        except ToolError as exc:
            return result_error(exc.user_message)
        except UnicodeDecodeError:
            return result_error("文件不是有效 UTF-8 文本。")
        except OSError as exc:
            return result_error(f"读取文件失败：{exc}")


class WriteFileTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="write_file",
            description="Write complete UTF-8 text content to a workspace file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path. Absolute paths are invalid; use values like `test.md`.",
                    },
                    "content": {"type": "string", "description": "Complete file content."},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        try:
            path = resolve_workspace_path(context.workspace_root, require_str(arguments, "path"))
            content = require_string(arguments, "content")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return result_ok("文件写入成功。", path=str(path), chars=len(content))
        except ToolError as exc:
            return result_error(exc.user_message)
        except OSError as exc:
            return result_error(f"写入文件失败：{exc}")


class EditFileTool:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="edit_file",
            description="Replace a uniquely matching original text fragment in a workspace file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path. Absolute paths are invalid; use values like `test.md`.",
                    },
                    "old_text": {"type": "string", "description": "Original text that must match exactly once."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        )

    def run(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        try:
            path = resolve_workspace_path(context.workspace_root, require_str(arguments, "path"))
            old_text = require_str(arguments, "old_text")
            new_text = require_string(arguments, "new_text")
            if not path.exists():
                return result_error("文件不存在。", path=str(path))
            content = path.read_text(encoding="utf-8")
            count = content.count(old_text)
            if count != 1:
                return result_error(f"old_text 匹配次数为 {count}，必须恰好为 1。", path=str(path), matches=count)
            updated = content.replace(old_text, new_text, 1)
            path.write_text(updated, encoding="utf-8")
            return result_ok("文件修改成功。", path=str(path), replacements=1)
        except ToolError as exc:
            return result_error(exc.user_message)
        except UnicodeDecodeError:
            return result_error("文件不是有效 UTF-8 文本。")
        except OSError as exc:
            return result_error(f"修改文件失败：{exc}")
