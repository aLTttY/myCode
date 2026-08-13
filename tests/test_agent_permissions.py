from mycode.agents.permissions import ChildPermissionFactory
from mycode.permissions.service import PermissionService
from mycode.types import ToolCall, ToolContext


def test_child_permissions_are_independent_and_noninteractive(tmp_path) -> None:
    parent = PermissionService.with_mode("default")
    entries_one = []
    entries_two = []
    factory = ChildPermissionFactory(parent)
    first = factory.create("default", entries_one.append)
    second = factory.create("strict", entries_two.append)
    context = ToolContext(tmp_path)
    call = ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})

    first_decision = first.authorize(call, context)
    second_decision = second.authorize(call, context)

    assert first_decision.reason_code == "noninteractive_approval_unavailable"
    assert second_decision.reason_code == "mode_deny"
    assert first.session_rule_count == 0
    assert second.session_rule_count == 0
    assert entries_one[0].tool_name == "write_file"
    assert entries_two[0].allowed is False
