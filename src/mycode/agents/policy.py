from __future__ import annotations

from dataclasses import dataclass

from mycode.tool_safety import READ_TOOLS
from mycode.tools.registry import ToolRegistry

from .models import AgentDefinition
from .parser import GLOBAL_CHILD_DENY


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    reason_code: str
    message: str


class ChildToolPolicy:
    def __init__(
        self,
        *,
        role: AgentDefinition | None,
        parent_mode: str,
        background_allowed_tools: tuple[str, ...],
    ) -> None:
        self.role = role
        self.parent_mode = parent_mode
        self.background_allowed_tools = frozenset(background_allowed_tools)

    def visible_registry(
        self,
        registry: ToolRegistry,
        *,
        background: bool,
    ) -> ToolRegistry:
        names = [
            name
            for name in registry.names()
            if self.authorize_call(name, background=background).allowed
        ]
        return registry.subset(names)

    def authorize_call(self, tool_name: str, *, background: bool) -> ToolPolicyDecision:
        if tool_name in GLOBAL_CHILD_DENY:
            return ToolPolicyDecision(
                False,
                "child_global_deny",
                f"子 Agent 不得调用控制工具 `{tool_name}`。",
            )
        if self.role is not None:
            if tool_name in self.role.denied_tools:
                return ToolPolicyDecision(
                    False,
                    "role_tool_deny",
                    f"Agent 角色禁止工具 `{tool_name}`。",
                )
            if tool_name not in self.role.allowed_tools:
                return ToolPolicyDecision(
                    False,
                    "role_tool_not_allowed",
                    f"Agent 角色未允许工具 `{tool_name}`。",
                )
        if self.parent_mode == "plan":
            if tool_name not in READ_TOOLS:
                return ToolPolicyDecision(
                    False,
                    "plan_mode_readonly",
                    "Plan 模式的子 Agent 只能调用只读工具。",
                )
        if background and tool_name not in self.background_allowed_tools:
            return ToolPolicyDecision(
                False,
                "background_tool_not_allowed",
                f"后台任务未允许工具 `{tool_name}`。",
            )
        return ToolPolicyDecision(True, "policy_allow", "子 Agent 工具策略允许调用。")
