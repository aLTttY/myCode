from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from mycode.instructions import InstructionBundle, InstructionLoader
from mycode.memory.storage import MemoryStore
from mycode.prompts.modes import DynamicInstruction
from mycode.tools.file_cache import FileReadCache
from mycode.types import ToolContext

from .models import InitializationResult, WorktreeLease


@dataclass(frozen=True)
class ChildWorkspaceContext:
    workspace_key: Path
    tool_context: ToolContext
    instruction_bundle: InstructionBundle
    project_memory_prompt: str
    isolation_instruction: DynamicInstruction


class WorkspaceContextFactory:
    def __init__(
        self,
        base_tool_context: ToolContext,
        *,
        instruction_loader: InstructionLoader | None = None,
    ) -> None:
        self.base_tool_context = base_tool_context
        self.instruction_loader = instruction_loader or InstructionLoader()

    def build(
        self,
        lease: WorktreeLease,
        initialization: InitializationResult,
    ) -> ChildWorkspaceContext:
        workspace = lease.workspace_root.resolve(strict=True)
        instructions = self.instruction_loader.load(
            workspace,
            user_root=workspace / ".mycode" / ".isolated-user-instructions",
        )
        project_memory = MemoryStore(workspace).read_index("project")
        isolation = DynamicInstruction(
            tag="mewcode_worktree_isolation",
            content=(
                f"当前子 Agent 的唯一工作目录是 {workspace}。\n"
                f"主工作区 {lease.identity.main_workspace} 不属于本任务边界。\n"
                "所有文件、搜索、命令、Git 和 Hook 操作必须使用已注入的显式 cwd；"
                "禁止跨目录访问或修改主工作区及其他 Worktree。"
            ),
            full=True,
        )
        tool_context = replace(
            self.base_tool_context,
            workspace_root=workspace,
            file_read_cache=FileReadCache(),
            process_environment=initialization.process_environment,
            excluded_roots=(),
        )
        return ChildWorkspaceContext(
            workspace_key=workspace,
            tool_context=tool_context,
            instruction_bundle=instructions,
            project_memory_prompt=project_memory,
            isolation_instruction=isolation,
        )
