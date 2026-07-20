from __future__ import annotations

import json
from collections.abc import Mapping

from mycode.tools.base import execution_result, truncate_text
from mycode.types import ToolContext, ToolExecutionResult, ToolResult, ToolSpec

from .manager import MCPManager
from .models import MCPManagerError, MCPRemoteTool


class MCPTool:
    def __init__(self, remote: MCPRemoteTool, manager: MCPManager) -> None:
        self.remote = remote
        self.manager = manager
        self._spec = ToolSpec(
            name=remote.exposed_name,
            description=remote.description,
            parameters=dict(remote.input_schema),
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    def run(
        self,
        arguments: Mapping[str, object],
        context: ToolContext,
    ) -> ToolResult | ToolExecutionResult:
        try:
            result = self.manager.call_tool(
                self.remote.server_name,
                self.remote.remote_name,
                arguments,
                context.timeout_seconds,
            )
        except MCPManagerError as exc:
            return self._failure(exc.reason_code, exc.user_message)
        except Exception as exc:  # noqa: BLE001 - adapter boundary must be structured.
            return self._failure(
                "adapter_error",
                f"MCP Server `{self.remote.server_name}` 调用失败（{type(exc).__name__}）。",
            )

        unsupported = sorted(
            {
                str(getattr(item, "type", "unknown"))
                for item in result.content
                if getattr(item, "type", None) != "text"
            }
        )
        if unsupported:
            return ToolResult(
                ok=False,
                message=f"MCP 工具返回了当前不支持的内容类型：{', '.join(unsupported)}。",
                data={
                    "server": self.remote.server_name,
                    "remote_tool": self.remote.remote_name,
                    "reason": "unsupported_content",
                    "content_types": unsupported,
                },
            )

        text = "\n".join(
            str(getattr(item, "text", ""))
            for item in result.content
            if getattr(item, "type", None) == "text"
        )
        full_text = text
        text, truncated = truncate_text(full_text, context.max_output_chars)
        structured = getattr(result, "structuredContent", None)
        structured_too_large = False
        if structured is not None:
            try:
                serialized = json.dumps(
                    structured,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            except (TypeError, ValueError):
                return self._failure(
                    "invalid_structured_content",
                    "MCP 工具返回的 structuredContent 不是有效 JSON 数据。",
                )
            if len(serialized) > context.max_output_chars:
                structured_too_large = True

        is_error = bool(getattr(result, "isError", False))
        full_message = full_text or ("MCP 工具返回错误。" if is_error else "MCP 工具调用成功。")
        complete_data: dict[str, object] = {
            "server": self.remote.server_name,
            "remote_tool": self.remote.remote_name,
        }
        if structured is not None:
            complete_data["structured_content"] = structured
        if is_error:
            complete_data["reason"] = "remote_error"
        complete = ToolResult(ok=not is_error, message=full_message, data=complete_data)

        if structured_too_large:
            display = self._failure(
                "result_too_large",
                "MCP 工具返回的 structuredContent 超过输出大小限制。",
            )
            return execution_result(display, complete)

        display_data = dict(complete_data)
        if truncated:
            display_data["truncated"] = True
        display_message = text or ("MCP 工具返回错误。" if is_error else "MCP 工具调用成功。")
        display = ToolResult(ok=not is_error, message=display_message, data=display_data)
        if not truncated:
            return execution_result(display)
        return execution_result(display, complete)

    def _failure(self, reason: str, message: str) -> ToolResult:
        return ToolResult(
            ok=False,
            message=message,
            data={
                "server": self.remote.server_name,
                "remote_tool": self.remote.remote_name,
                "reason": reason,
            },
        )
