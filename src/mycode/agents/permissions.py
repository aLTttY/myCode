from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from mycode.permissions.approval import DenyApprovalHandler
from mycode.permissions.models import PermissionDecision
from mycode.permissions.service import PermissionService
from mycode.types import ToolCall, ToolContext

from .models import ChildPermissionMode, PermissionAuditEntry


class _AuditedPermissionService(PermissionService):
    def __init__(self, *args: object, audit_sink: Callable[[PermissionAuditEntry], None], **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._audit_sink = audit_sink

    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        decision = super().authorize(call, context)
        if decision.reason_code == "user_denied":
            decision = PermissionDecision(
                False,
                "noninteractive_approval_unavailable",
                "子 Agent 非交互执行，无法请求人工审批，已安全拒绝。",
                decision.target,
                decision.matched_source,
                decision.matched_rule,
            )
        try:
            self._audit_sink(
                PermissionAuditEntry(
                    occurred_at=datetime.now(timezone.utc),
                    tool_name=call.name,
                    allowed=decision.allowed,
                    reason_code=decision.reason_code,
                )
            )
        except Exception:
            pass
        return decision


class ChildPermissionFactory:
    def __init__(
        self,
        parent: PermissionService,
        *,
        mcp_tool_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.parent = parent
        self.mcp_tool_prefixes = mcp_tool_prefixes

    def create(
        self,
        mode: ChildPermissionMode,
        audit_sink: Callable[[PermissionAuditEntry], None],
    ) -> PermissionService:
        effective = self.parent.config.effective_mode if mode == "inherit" else mode
        config = replace(self.parent.config, effective_mode=effective)
        return _AuditedPermissionService(
            config,
            DenyApprovalHandler(),
            self.mcp_tool_prefixes,
            audit_sink=audit_sink,
        )
