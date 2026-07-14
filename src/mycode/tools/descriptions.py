from __future__ import annotations

from collections.abc import Sequence

from mycode.types import ToolSpec


DEDICATED_RULES = {
    "read_file": "Use this tool first when you need to inspect a known workspace file.",
    "find_files": "Use this tool first when you need to locate files by name or path pattern.",
    "search_code": "Use this tool first when you need to find code or text occurrences in the workspace.",
    "edit_file": "Use this tool to modify an existing file after reading or searching to confirm its current content.",
    "write_file": "Use this tool to create or fully replace a workspace file only when complete content is available.",
    "run_command": "Use this tool only when a shell command is the appropriate way to inspect or verify the task.",
}

WORKSPACE_RULE = "Stay inside the workspace; do not use paths or commands unrelated to the current task."
EDIT_FIRST_READ_RULE = "Before editing, read the target file or search relevant code to confirm the current content."


def reinforce_tool_spec(spec: ToolSpec) -> ToolSpec:
    additions: list[str] = []
    dedicated_rule = DEDICATED_RULES.get(spec.name)
    if dedicated_rule:
        additions.append(dedicated_rule)
    if spec.name == "edit_file":
        additions.append(EDIT_FIRST_READ_RULE)
    if spec.name in {"read_file", "write_file", "edit_file", "run_command", "find_files", "search_code"}:
        additions.append(WORKSPACE_RULE)
    if not additions:
        return spec
    description = spec.description.rstrip()
    reinforced = " ".join([description, *additions])
    return ToolSpec(name=spec.name, description=reinforced, parameters=spec.parameters)


def reinforce_tool_specs(specs: Sequence[ToolSpec]) -> tuple[ToolSpec, ...]:
    return tuple(reinforce_tool_spec(spec) for spec in specs)
