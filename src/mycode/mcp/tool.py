from __future__ import annotations

import json
from collections.abc import Mapping

from mycode.tools.base import truncate_text
from mycode.types import ToolContext, ToolResult, ToolSpec

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
    ) -> ToolResult:
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
        text, truncated = truncate_text(text, context.max_output_chars)
        structured = getattr(result, "structuredContent", None)
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
                return self._failure(
                    "result_too_large",
                    "MCP 工具返回的 structuredContent 超过输出大小限制。",
                )

        is_error = bool(getattr(result, "isError", False))
        message = text or ("MCP 工具返回错误。" if is_error else "MCP 工具调用成功。")
        data: dict[str, object] = {
            "server": self.remote.server_name,
            "remote_tool": self.remote.remote_name,
        }
        if structured is not None:
            data["structured_content"] = structured
        if truncated:
            data["truncated"] = True
        if is_error:
            data["reason"] = "remote_error"
        return ToolResult(ok=not is_error, message=message, data=data)

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
