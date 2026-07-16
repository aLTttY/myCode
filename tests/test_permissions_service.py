from collections.abc import Iterable
from pathlib import Path

import pytest

from mycode.permissions.models import PermissionConfigSet, PermissionLayer
from mycode.permissions.rules import parse_rule
from mycode.permissions.service import PermissionService
from mycode.types import ToolCall, ToolContext


TOOLS = {"read_file", "write_file", "edit_file", "run_command", "find_files", "search_code"}


class FakeApproval:
    def __init__(self, choices: Iterable[str]) -> None:
        self.choices = iter(choices)
        self.calls = []

    def request(self, approval):
        self.calls.append(approval)
        return next(self.choices)


def config(mode="default", *, user=(), project=(), local=()) -> PermissionConfigSet:
    return PermissionConfigSet(
        user=PermissionLayer("user", rules=tuple(user)),
        project=PermissionLayer("project", rules=tuple(project)),
        local=local if isinstance(local, PermissionLayer) else PermissionLayer("local", rules=tuple(local)),
        effective_mode=mode,
    )


def call(name: str, **arguments: object) -> ToolCall:
    return ToolCall("1", name, arguments)


def test_modes_apply_only_to_controlled_tools(tmp_path: Path) -> None:
    context = ToolContext(tmp_path)
    assert not PermissionService(config("strict")).authorize(call("write_file", path="a.txt"), context).allowed
    assert PermissionService(config("allow")).authorize(call("write_file", path="a.txt"), context).allowed


@pytest.mark.parametrize("mode", ["strict", "default", "allow"])
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("read_file", {"path": "a.txt"}),
        ("find_files", {"pattern": "*.py"}),
        ("search_code", {"query": "agent"}),
    ],
)
def test_read_tools_auto_allow_in_every_mode(tmp_path: Path, mode: str, tool: str, arguments: dict[str, object]) -> None:
    approval = FakeApproval(["deny"])
    decision = PermissionService(config(mode), approval).authorize(call(tool, **arguments), ToolContext(tmp_path))

    assert decision.allowed and decision.reason_code == "readonly_allow"
    assert not approval.calls


def test_read_tool_ignores_deny_rule(tmp_path: Path) -> None:
    rule = parse_rule("read_file(**)", "deny", "local", TOOLS)
    decision = PermissionService(config("strict", local=(rule,))).authorize(
        call("read_file", path="a.txt"), ToolContext(tmp_path)
    )

    assert decision.allowed and decision.reason_code == "readonly_allow"


def test_explicit_deny_skips_approval_even_in_allow_mode(tmp_path: Path) -> None:
    approval = FakeApproval(["allow_once"])
    rule = parse_rule("run_command(git *)", "deny", "project", TOOLS)
    decision = PermissionService(config("allow", project=(rule,)), approval).authorize(
        call("run_command", command="git status"), ToolContext(tmp_path)
    )
    assert not decision.allowed and decision.reason_code == "rule_deny"
    assert not approval.calls


def test_blacklist_and_sandbox_cannot_be_overridden(tmp_path: Path) -> None:
    allow_all = parse_rule("run_command(*)", "allow", "local", TOOLS)
    service = PermissionService(config("allow", local=(allow_all,)), FakeApproval(["allow_once"]))
    blacklisted = service.authorize(call("run_command", command="rm -rf /"), ToolContext(tmp_path))
    escaped = service.authorize(call("run_command", command="cat /etc/passwd"), ToolContext(tmp_path))
    assert blacklisted.reason_code == "blacklisted" and not blacklisted.allowed
    assert escaped.reason_code == "sandbox_escape" and not escaped.allowed


def test_default_mode_supports_once_and_deny(tmp_path: Path) -> None:
    approval = FakeApproval(["allow_once", "deny"])
    service = PermissionService(config(), approval)
    first = service.authorize(call("write_file", path="a.txt"), ToolContext(tmp_path))
    second = service.authorize(call("write_file", path="a.txt"), ToolContext(tmp_path))
    assert first.allowed and first.reason_code == "user_allow_once"
    assert not second.allowed and second.reason_code == "user_denied"
    assert len(approval.calls) == 2


def test_session_allow_lasts_only_for_service_instance(tmp_path: Path) -> None:
    approval = FakeApproval(["allow_session"])
    service = PermissionService(config(), approval)
    tool_call = call("write_file", path="a.txt")
    assert service.authorize(tool_call, ToolContext(tmp_path)).allowed
    assert service.authorize(tool_call, ToolContext(tmp_path)).reason_code == "rule_allow"
    assert len(approval.calls) == 1

    fresh_approval = FakeApproval(["deny"])
    fresh = PermissionService(config(), fresh_approval)
    assert not fresh.authorize(tool_call, ToolContext(tmp_path)).allowed


def test_session_allow_prevents_second_write_approval(tmp_path: Path) -> None:
    approval = FakeApproval(["allow_session"])
    service = PermissionService(config(), approval)
    tool_call = call("write_file", path="hello.md")

    first = service.authorize(tool_call, ToolContext(tmp_path))
    second = service.authorize(tool_call, ToolContext(tmp_path))

    assert first.reason_code == "user_allow_session"
    assert second.reason_code == "rule_allow"
    assert len(approval.calls) == 1


def test_manual_local_rule_is_loaded_by_fresh_service(tmp_path: Path) -> None:
    local_rule = parse_rule("run_command(git status)", "allow", "local", TOOLS)
    fresh = PermissionService(config(local=(local_rule,)), FakeApproval([]))

    assert fresh.authorize(call("run_command", command="git status"), ToolContext(tmp_path)).reason_code == "rule_allow"


def test_missing_approval_handler_denies_default_mode(tmp_path: Path) -> None:
    decision = PermissionService(config()).authorize(call("write_file", path="a.txt"), ToolContext(tmp_path))
    assert not decision.allowed and decision.reason_code == "user_denied"


def test_run_command_ls_still_requires_approval(tmp_path: Path) -> None:
    approval = FakeApproval(["deny"])
    decision = PermissionService(config(), approval).authorize(
        call("run_command", command="ls -la"), ToolContext(tmp_path)
    )

    assert not decision.allowed and decision.reason_code == "user_denied"
    assert len(approval.calls) == 1
