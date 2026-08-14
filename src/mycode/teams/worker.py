from __future__ import annotations

import argparse
import signal
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from mycode.agent.config import AgentConfig, AgentRequest
from mycode.agent.runner import AgentRunner
from mycode.config import load_config
from mycode.instructions import InstructionBundle, InstructionLoader
from mycode.permissions.config import PermissionConfigLoader
from mycode.permissions.service import PermissionService
from mycode.providers.factory import create_provider
from mycode.tool_safety import READ_TOOLS, SYSTEM_TOOLS
from mycode.tools.registry import create_default_registry
from mycode.types import Message, ToolContext

from .identity import WorkerTicketManager
from .member import MemberAgentResult, MemberRunRequest
from .models import TeamError
from .runtime import TeamRuntime


class _WorkerMemberAgent:
    def __init__(self, identity, runtime: TeamRuntime, config, workspace: Path) -> None:
        self.identity = identity
        self.runtime = runtime
        self.config = config
        self.workspace = workspace
        self.base_registry = create_default_registry()
        known_tools = set(self.base_registry.names()) | set(SYSTEM_TOOLS)
        permission_config = PermissionConfigLoader(known_tools).load(workspace, None)
        self.permissions = PermissionService(permission_config)
        self.instructions = InstructionLoader().load(workspace)

    def run(self, request: MemberRunRequest) -> MemberAgentResult:
        member = self.runtime.store.load(self.identity.team_name).team.members[self.identity.member_id]
        role = member.role
        allowed = set(role.allowed_tools or self.base_registry.names()) - set(role.denied_tools)
        allowed -= {"Agent", "Task", "load_skill"}
        if not member.writable or (request.approval_required and not request.approval_effective):
            allowed &= set(READ_TOOLS)
        registry = self.runtime.tools.for_member(
            self.base_registry, self.identity,
            tuple(name for name in self.base_registry.names() if name in allowed),
        )
        model_id = self.config.model if role.model == "inherit" else self.config.agents.model_aliases[role.model]
        provider_config = self.config if model_id == self.config.model else replace(self.config, model=model_id)
        provider = create_provider(provider_config)
        bundle = InstructionBundle(
            content=(role.system_prompt + "\n\n" + self.instructions.content).strip(),
            loaded_files=self.instructions.loaded_files,
            warnings=self.instructions.warnings,
        )
        runner = AgentRunner(
            provider, registry, ToolContext(workspace_root=request.workspace),
            AgentConfig(max_iterations=role.max_iterations), self.permissions,
            self.config.context, instruction_bundle=bundle,
            restored_messages=request.context,
        )
        task = ""
        if request.task_id:
            task = f"任务 {request.task_id}: {request.task_title}\n{request.task_description}\n"
        inbox = "\n\n".join(message.content for message in request.inbox_messages)
        gate = "计划尚未获批，不得修改文件。\n" if request.approval_required and not request.approval_effective else ""
        try:
            for _ in runner.run(AgentRequest((task + gate + inbox).strip() or "检查团队邮箱并报告状态。")):
                pass
            messages = tuple(runner.messages[len(request.context):])
            summary = next((item.content for item in reversed(messages) if item.role == "assistant"), "")
            return MemberAgentResult(messages, summary)
        finally:
            runner.close()
            close = getattr(provider, "close", None)
            if close is not None:
                close()


def worker_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="mycode team-worker", add_help=False)
    parser.add_argument("--team", required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--ticket-secret", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)
    wake_event = threading.Event()
    signal.signal(signal.SIGUSR1, lambda _signum, _frame: wake_event.set())
    try:
        config = load_config(args.config)
        tickets = WorkerTicketManager()
        # Ticket validation happens before any model/provider or team mutation.
        from .storage import FileTeamStore
        store = FileTeamStore(config=config.teams)
        aggregate = store.load(args.team)
        tickets.consume(
            Path(args.ticket), args.ticket_secret, team_name=args.team,
            member_id=args.member, repository_id=aggregate.team.repository_id,
        )
        member = aggregate.team.members.get(args.member)
        if member is None:
            raise TeamError("member_not_found", "Worker 成员不在团队花名册中。")
        runtime = TeamRuntime(
            config, Path(aggregate.team.workspace_root), lambda _name: member.role,
        )
        identity = runtime.authority.issue_member(
            args.team, member.member_id, member.name, aggregate.team.repository_id,
        )
        runtime.member_runtime.agent_factory = lambda actor: _WorkerMemberAgent(
            actor, runtime, config, Path(aggregate.team.workspace_root)
        )
        try:
            while True:
                runtime.member_runtime.run(identity)
                wake_event.wait()
                wake_event.clear()
        finally:
            runtime.authority.revoke(identity)
            runtime.close()
    except Exception as exc:
        message = getattr(exc, "user_message", type(exc).__name__)
        print(f"team-worker failed: {message}", file=sys.stderr)
        return 1
