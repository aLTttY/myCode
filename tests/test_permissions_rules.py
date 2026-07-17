from pathlib import Path

import pytest

from mycode.permissions.models import PermissionLayer, PermissionRequest
from mycode.permissions.rules import RuleEngine, parse_rule


TOOLS = {"read_file", "write_file", "run_command"}


def request(tool: str, target: str) -> PermissionRequest:
    return PermissionRequest("1", tool, target, {}, Path("/workspace"))


def test_parse_rule_detects_exact_and_glob() -> None:
    exact = parse_rule("read_file(README.md)", "allow", "user", TOOLS)
    glob = parse_rule("run_command(git *)", "allow", "user", TOOLS)

    assert exact.match_type == "exact"
    assert glob.match_type == "glob"


@pytest.mark.parametrize("value", ["", "read_file", "(x)", "read_file()", "read_file(x) trailing"])
def test_parse_rule_rejects_invalid_syntax(value: str) -> None:
    with pytest.raises(ValueError):
        parse_rule(value, "allow", "user", TOOLS)


def test_parse_rule_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError, match="未知工具"):
        parse_rule("missing(x)", "allow", "user", TOOLS)


def test_exact_beats_glob_in_same_layer() -> None:
    layer = PermissionLayer(
        "project",
        rules=(
            parse_rule("read_file(*)", "deny", "project", TOOLS),
            parse_rule("read_file(README.md)", "allow", "project", TOOLS),
        ),
    )

    decision = RuleEngine().decide(request("read_file", "README.md"), (layer,))

    assert decision is not None and decision.allowed
    assert decision.matched_rule and decision.matched_rule.match_type == "exact"


def test_deny_beats_allow_for_equal_match_type() -> None:
    layer = PermissionLayer(
        "project",
        rules=(
            parse_rule("run_command(git *)", "allow", "project", TOOLS),
            parse_rule("run_command(git *)", "deny", "project", TOOLS),
        ),
    )

    decision = RuleEngine().decide(request("run_command", "git status"), (layer,))

    assert decision is not None and not decision.allowed


def test_highest_matching_layer_wins() -> None:
    session = PermissionLayer("session", rules=(parse_rule("read_file(*)", "allow", "session", TOOLS),))
    local = PermissionLayer("local", rules=(parse_rule("read_file(README.md)", "deny", "local", TOOLS),))

    decision = RuleEngine().decide(request("read_file", "README.md"), (session, local))

    assert decision is not None and decision.allowed
    assert decision.matched_source == "session"


def test_no_matching_rule_returns_none() -> None:
    layer = PermissionLayer("user", rules=(parse_rule("write_file(*)", "allow", "user", TOOLS),))
    assert RuleEngine().decide(request("read_file", "README.md"), (layer,)) is None


def test_parse_rule_accepts_configured_mcp_namespace_and_hyphen() -> None:
    rule = parse_rule(
        "github__create-issue(call)",
        "allow",
        "project",
        TOOLS,
        ("github__",),
    )

    assert rule.tool == "github__create-issue"
    assert rule.match_type == "exact"
