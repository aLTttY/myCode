from __future__ import annotations

from threading import RLock

from mycode.matching import parse_match_pattern
from mycode.tool_safety import is_read_tool, is_system_tool
from mycode.types import ToolCall, ToolContext

from .approval import ApprovalHandler, DenyApprovalHandler
from .blacklist import is_blacklisted
from .models import (
    ApprovalPrompt,
    PermissionConfigSet,
    PermissionDecision,
    PermissionLayer,
    PermissionMode,
    PermissionRule,
    PermissionValidationError,
)
from .rules import RuleEngine
from .sandbox import validate_command_paths
from .targets import PermissionTargetResolver


class PermissionService:
    def __init__(
        self,
        config: PermissionConfigSet,
        approval_handler: ApprovalHandler | None = None,
        mcp_tool_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.config = config
        self.approval_handler = approval_handler or DenyApprovalHandler()
        self._session_rules: list[PermissionRule] = []
        self._lock = RLock()
        self._resolver = PermissionTargetResolver(mcp_tool_prefixes)
        self._rules = RuleEngine()

    @classmethod
    def with_mode(
        cls,
        mode: PermissionMode = "default",
        approval_handler: ApprovalHandler | None = None,
        mcp_tool_prefixes: tuple[str, ...] = (),
    ) -> "PermissionService":
        if mode not in {"strict", "default", "allow"}:
            raise ValueError("权限模式必须是 strict、default 或 allow。")
        config = PermissionConfigSet(
            user=PermissionLayer("user"),
            project=PermissionLayer("project"),
            local=PermissionLayer("local"),
            effective_mode=mode,
        )
        return cls(config, approval_handler, mcp_tool_prefixes)

    def authorize(self, call: ToolCall, context: ToolContext) -> PermissionDecision:
        if is_system_tool(call.name):
            return PermissionDecision(
                True,
                "system_tool_allow",
                "系统能力选择工具已自动允许；业务工具仍需单独授权。",
                "system",
            )
        try:
            request = self._resolver.resolve(call, context.workspace_root)
        except PermissionValidationError as exc:
            return PermissionDecision(False, exc.reason_code, exc.message, exc.target)

        if is_read_tool(call.name):
            return PermissionDecision(
                True,
                "readonly_allow",
                "专用只读工具已通过工作区校验并自动允许。",
                request.target,
            )

        if call.name == "run_command":
            command = request.target
            if is_blacklisted(command):
                return PermissionDecision(
                    False,
                    "blacklisted",
                    "命令命中不可覆盖的危险操作黑名单。",
                    command,
                )
            try:
                validate_command_paths(command, request.workspace_root)
            except PermissionValidationError as exc:
                return PermissionDecision(False, exc.reason_code, exc.message, exc.target or command)

        with self._lock:
            session = PermissionLayer(source="session", rules=tuple(self._session_rules))
            decision = self._rules.decide(
                request,
                (session, self.config.local, self.config.project, self.config.user),
            )
            if decision is not None:
                return decision

            mode = self.config.effective_mode
            if mode == "strict":
                return PermissionDecision(False, "mode_deny", "strict 权限模式拒绝未匹配规则的调用。", request.target)
            if mode == "allow":
                return PermissionDecision(True, "mode_allow", "allow 权限模式允许未匹配规则的调用。", request.target)

            approval = ApprovalPrompt(
                tool=request.tool,
                target=request.target,
                reason="没有权限规则明确允许或拒绝此调用。",
            )
            try:
                choice = self.approval_handler.request(approval)
            except KeyboardInterrupt:
                raise
            except Exception:
                choice = "deny"

            if choice == "deny":
                return PermissionDecision(False, "user_denied", "用户拒绝了工具调用。", request.target)
            if choice == "allow_once":
                return PermissionDecision(True, "user_allow_once", "用户允许本次工具调用。", request.target)

            rule = PermissionRule(
                tool=request.tool,
                matcher=parse_match_pattern(request.target),
                effect="allow",
                source="session" if choice == "allow_session" else "local",
            )
            if choice == "allow_session":
                if rule not in self._session_rules:
                    self._session_rules.append(rule)
                return PermissionDecision(True, "user_allow_session", "用户允许本会话内的相同调用。", request.target)

            return PermissionDecision(False, "invalid_approval", "审批结果无效，已安全拒绝。", request.target)

    @property
    def session_rule_count(self) -> int:
        with self._lock:
            return len(self._session_rules)

    def update_dynamic_call_tools(self, names: set[str] | frozenset[str]) -> None:
        self._resolver.update_dynamic_call_tools(names)
