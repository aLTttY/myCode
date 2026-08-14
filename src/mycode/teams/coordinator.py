from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from mycode.types import TeamConfig, ToolContext, ToolExecutionResult, ToolResult

from .binding import TeamBinding, coordinator_enabled
from .integration import IntegrationService, ScopedIntegrationGitExecutor
from .models import TeamError


CONTROL = re.compile(r"[\x00\r\n;&|<>`$]")


@dataclass(frozen=True)
class CoordinatorCommandDecision:
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: float
    kind: str


@dataclass(frozen=True)
class ScopedGitDecision:
    integration_id: str
    operation: str


class CoordinatorCommandPolicy:
    def __init__(
        self,
        config: TeamConfig,
        integration: IntegrationService,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self.integration = integration
        self.environment = dict(os.environ if environment is None else environment)
        self.scoped_git: ScopedIntegrationGitExecutor = integration.scoped_git

    def validate_read(self, argv: Sequence[str], binding: TeamBinding) -> CoordinatorCommandDecision:
        self._require_enabled(binding)
        args = tuple(argv)
        if not args or len(args) > 128 or any(not arg or len(arg) > 4096 or CONTROL.search(arg) for arg in args):
            raise TeamError("coordinator_command_rejected", "Coordinator 只接受安全的 argv 数组。")
        command = args[0]
        workspace = Path(self.integration.store.load(binding.team_name).team.workspace_root)
        if command == "pwd" and len(args) == 1:
            return CoordinatorCommandDecision(args, workspace, 10.0, "read")
        if command == "rg" and not any(
            arg.startswith("--pre") or arg in {"-z", "--search-zip", ".."}
            or arg.startswith("/")
            for arg in args[1:]
        ):
            return CoordinatorCommandDecision(args, workspace, 30.0, "read")
        if command == "git" and len(args) >= 2:
            allowed = {"status", "diff", "log", "show", "rev-parse", "branch"}
            if args[1] in allowed and not any(arg.startswith("--config") or "ext::" in arg for arg in args[2:]):
                if args[1] != "branch" or args[2:] == ("--show-current",):
                    return CoordinatorCommandDecision(args, workspace, 30.0, "read")
        raise TeamError("coordinator_command_rejected", "命令不在 Coordinator 只读白名单中。")

    def resolve_verification(self, command_id: str, binding: TeamBinding) -> CoordinatorCommandDecision:
        self._require_enabled(binding)
        command = next((item for item in self.config.verification_commands if item.command_id == command_id), None)
        if command is None:
            raise TeamError("verification_not_found", "验证命令 ID 未配置。")
        aggregate = self.integration.store.load(binding.team_name)
        active = [item for item in aggregate.integrations.values() if item.status in {"validating", "ready_to_advance"}]
        if len(active) != 1:
            raise TeamError("integration_scope_required", "验证命令必须绑定唯一活动集成。")
        return CoordinatorCommandDecision(command.argv, Path(active[0].integration_worktree), command.timeout_seconds, "verification")

    def resolve_git_operation(
        self, integration_id: str, operation: str, binding: TeamBinding
    ) -> ScopedGitDecision:
        self._require_enabled(binding)
        if operation not in ScopedIntegrationGitExecutor.OPERATIONS:
            raise TeamError("invalid_git_operation", "Git operation 不在固定白名单中。")
        self.integration.get(binding.actor, integration_id)
        return ScopedGitDecision(integration_id, operation)

    def execute(
        self, decision: CoordinatorCommandDecision, context: ToolContext
    ) -> ToolExecutionResult:
        before = None
        if decision.kind == "verification":
            before = self._git_status(decision.cwd)
            if before:
                result = ToolResult(False, "验证前集成工作区不干净。", {"reason_code": "integration_dirty"})
                return ToolExecutionResult.same(result)
        try:
            completed = subprocess.run(
                decision.argv, cwd=decision.cwd, shell=False, capture_output=True,
                timeout=decision.timeout_seconds, check=False,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = ToolResult(False, f"Coordinator 命令执行失败：{type(exc).__name__}", {"reason_code": "command_failed"})
            return ToolExecutionResult.same(result)
        output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
        if decision.kind == "verification" and self._git_status(decision.cwd) != before:
            result = ToolResult(False, "验证命令修改了集成工作区，结果已拒绝。", {"reason_code": "verification_modified_workspace"})
            return ToolExecutionResult.same(result)
        if len(output) > context.max_output_chars:
            output = output[-context.max_output_chars:]
        result = ToolResult(
            completed.returncode == 0,
            "Coordinator 命令完成。" if completed.returncode == 0 else "Coordinator 命令返回非零状态。",
            {"returncode": completed.returncode, "output": output},
        )
        return ToolExecutionResult.same(result)

    @staticmethod
    def _git_status(cwd: Path) -> bytes:
        result = subprocess.run(
            ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all"),
            cwd=cwd, shell=False, capture_output=True, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        )
        return result.stdout if result.returncode == 0 else b"git-status-failed"

    @staticmethod
    def _require_enabled(binding: TeamBinding) -> None:
        if not binding.coordinator_enabled:
            raise TeamError("coordinator_disabled", f"Coordinator 未启用：{binding.coordinator_reason}")
