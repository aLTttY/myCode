from __future__ import annotations

import json
from pathlib import Path

import pytest

from mycode.permissions.service import PermissionService
from mycode.skills.models import SkillToolDefinition, immutable_mapping
from mycode.skills.tools import SkillScriptTool
from mycode.tools.executor import ToolExecutor
from mycode.tools.registry import ToolRegistry
from mycode.types import ToolCall, ToolContext


def _definition(script: Path) -> SkillToolDefinition:
    return SkillToolDefinition(
        local_name="probe",
        exposed_name="demo__probe",
        description="probe",
        parameters=immutable_mapping({"type": "object"}),
        script_path=script,
        fingerprint="fp",
    )


def _script(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "tool.py"
    path.write_text(content, encoding="utf-8")
    return path


def test_script_tool_receives_arguments_workspace_and_minimal_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_API_KEY", "must-not-leak")
    script = _script(
        tmp_path,
        """import json, os, sys
payload = json.load(sys.stdin)
result = {
    "arguments": payload["arguments"],
    "workspace": payload["context"]["workspace_root"],
    "cwd": os.getcwd(),
    "secret_present": "SENTINEL_API_KEY" in os.environ,
    "overlay": os.environ.get("MEWCODE_TASK_OVERLAY"),
}
print(json.dumps({"ok": True, "message": "done", "data": result}))
""",
    )
    tool = SkillScriptTool(_definition(script))

    result = tool.run(
        {"query": "中文"},
        ToolContext(
            tmp_path,
            process_environment={"MEWCODE_TASK_OVERLAY": "worktree"},
        ),
    )

    assert result.ok
    assert result.data["arguments"] == {"query": "中文"}
    assert result.data["workspace"] == str(tmp_path.resolve())
    assert result.data["cwd"] == str(tmp_path)
    assert result.data["secret_present"] is False
    assert result.data["overlay"] == "worktree"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("", "empty_output"),
        ("print('not-json')\n", "invalid_json"),
        ("print('{}')\n", "invalid_result"),
        ("import sys; sys.exit(3)\n", "nonzero_exit"),
        ("import sys; sys.stdout.buffer.write(b'\\xff')\n", "invalid_utf8"),
    ],
)
def test_script_tool_returns_safe_structured_failures(
    tmp_path: Path,
    body: str,
    reason: str,
) -> None:
    tool = SkillScriptTool(_definition(_script(tmp_path, body)))

    result = tool.run({}, ToolContext(tmp_path))

    assert not result.ok
    assert result.data["reason"] == reason
    assert "not-json" not in result.message


def test_script_tool_times_out_and_limits_output(tmp_path: Path) -> None:
    timeout_tool = SkillScriptTool(
        _definition(_script(tmp_path, "import time; time.sleep(5)\n"))
    )
    timeout = timeout_tool.run({}, ToolContext(tmp_path, timeout_seconds=0.05))
    assert timeout.data["reason"] == "timeout"

    large_tool = SkillScriptTool(
        _definition(_script(tmp_path, "print('x' * 10000)\n"))
    )
    large = large_tool.run({}, ToolContext(tmp_path, max_output_chars=50))
    assert large.data["reason"] == "output_too_large"


def test_script_tool_rechecks_script_symlink(tmp_path: Path) -> None:
    target = _script(tmp_path, "print('{}')\n")
    link = tmp_path / "link.py"
    link.symlink_to(target)
    result = SkillScriptTool(_definition(link)).run({}, ToolContext(tmp_path))
    assert result.data["reason"] == "script_unavailable"


class Approval:
    def __init__(self, choice: str) -> None:
        self.choice = choice
        self.calls = 0

    def request(self, prompt):
        self.calls += 1
        return self.choice


def test_script_tool_runs_through_side_effect_permission(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "import json; print(json.dumps({'ok': True, 'message': 'ok', 'data': {}}))\n",
    )
    registry = ToolRegistry()
    registry.register(SkillScriptTool(_definition(script)))

    denied_approval = Approval("deny")
    denied_service = PermissionService.with_mode("default", denied_approval)
    denied_service.update_dynamic_call_tools({"demo__probe"})
    denied = ToolExecutor(registry, ToolContext(tmp_path), denied_service).execute(
        ToolCall("1", "demo__probe", {})
    )
    assert not denied.ok
    assert denied_approval.calls == 1

    allowed_approval = Approval("allow_once")
    allowed_service = PermissionService.with_mode("default", allowed_approval)
    allowed_service.update_dynamic_call_tools({"demo__probe"})
    allowed = ToolExecutor(registry, ToolContext(tmp_path), allowed_service).execute(
        ToolCall("2", "demo__probe", {})
    )
    assert allowed.ok
    assert allowed_approval.calls == 1
