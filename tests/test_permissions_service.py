from collections.abc import Iterable
from pathlib import Path

from mycode.permissions.config import LocalRuleStore
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


def test_modes_apply_only_when_rules_do_not_match(tmp_path: Path) -> None:
    context = ToolContext(tmp_path)
    assert not PermissionService(config("strict")).authorize(call("read_file", path="a.txt"), context).allowed
    assert PermissionService(config("allow")).authorize(call("read_file", path="a.txt"), context).allowed


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
    first = service.authorize(call("read_file", path="a.txt"), ToolContext(tmp_path))
    second = service.authorize(call("read_file", path="a.txt"), ToolContext(tmp_path))
    assert first.allowed and first.reason_code == "user_allow_once"
    assert not second.allowed and second.reason_code == "user_denied"
    assert len(approval.calls) == 2


def test_session_allow_lasts_only_for_service_instance(tmp_path: Path) -> None:
    approval = FakeApproval(["allow_session"])
    service = PermissionService(config(), approval)
    tool_call = call("read_file", path="a.txt")
    assert service.authorize(tool_call, ToolContext(tmp_path)).allowed
    assert service.authorize(tool_call, ToolContext(tmp_path)).reason_code == "rule_allow"
    assert len(approval.calls) == 1

    fresh_approval = FakeApproval(["deny"])
    fresh = PermissionService(config(), fresh_approval)
    assert not fresh.authorize(tool_call, ToolContext(tmp_path)).allowed


def test_permanent_allow_is_loaded_by_fresh_service(tmp_path: Path) -> None:
    local_path = tmp_path / ".mycode/permissions.local.yaml"
    approval = FakeApproval(["allow_permanent"])
    service = PermissionService(config(), approval, LocalRuleStore(local_path, TOOLS))
    tool_call = call("run_command", command="git status")

    assert service.authorize(tool_call, ToolContext(tmp_path)).reason_code == "user_allow_permanent"
    local_layer = LocalRuleStore(local_path, TOOLS).add_exact_allow("run_command", "git status")
    fresh = PermissionService(config(local=local_layer), FakeApproval([]))
    assert fresh.authorize(tool_call, ToolContext(tmp_path)).reason_code == "rule_allow"


def test_missing_approval_handler_denies_default_mode(tmp_path: Path) -> None:
    decision = PermissionService(config()).authorize(call("read_file", path="a.txt"), ToolContext(tmp_path))
    assert not decision.allowed and decision.reason_code == "user_denied"
