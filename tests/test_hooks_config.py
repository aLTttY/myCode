from pathlib import Path

import pytest

from mycode.hooks.config import HookConfigLoader
from mycode.hooks.models import AgentAction, CommandAction, HTTPAction, PromptAction
from mycode.types import ConfigError


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_missing_files_produce_empty_snapshot(tmp_path: Path) -> None:
    snapshot = HookConfigLoader(tmp_path / "home").load(tmp_path / "workspace")
    assert snapshot.rules == ()


def test_loads_three_layers_in_source_and_declaration_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    write(
        home / ".mycode/hooks.yaml",
        "hooks:\n"
        "  - event: session_start\n"
        "    action: {type: command, command: user-one}\n"
        "  - event: turn_start\n"
        "    action: {type: prompt, content: user-two}\n",
    )
    write(
        workspace / ".mycode/hooks.yaml",
        "hooks:\n  - event: message_received\n    action: {type: http, url: https://example.com}\n",
    )
    write(
        workspace / ".mycode/hooks.local.yaml",
        "hooks:\n  - event: turn_end\n    action: {type: agent, prompt: summarize}\n",
    )

    snapshot = HookConfigLoader(home).load(workspace)

    assert [rule.rule_id for rule in snapshot.rules] == [
        "user:1",
        "user:2",
        "project:1",
        "local:1",
    ]
    assert [rule.source for rule in snapshot.rules] == ["user", "user", "project", "local"]
    assert [rule.source_index for rule in snapshot.rules] == [1, 2, 1, 1]
    assert snapshot.rules[0].source_path == home / ".mycode/hooks.yaml"
    assert snapshot.rules[-1].source_path == workspace.resolve() / ".mycode/hooks.local.yaml"


def test_loads_all_actions_conditions_and_defaults(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    write(
        workspace / ".mycode/hooks.yaml",
        "hooks:\n"
        "  - event: tool_before\n"
        "    if:\n"
        "      all:\n"
        "        - tool.name(run_command)\n"
        "        - '!tool.arguments.command(glob:safe/*)'\n"
        "    action:\n"
        "      type: command\n"
        "      command: check\n"
        "      timeout_seconds: 0.1\n"
        "      once: true\n"
        "  - event: tool_after\n"
        "    action:\n"
        "      type: http\n"
        "      url: https://example.com:8443/hooks\n"
        "      method: patch\n"
        "      headers: {X-Test: yes}\n"
        "      async: true\n"
        "  - event: turn_start\n"
        "    action: {type: prompt, content: remember}\n"
        "  - event: agent_error\n"
        "    action: {type: agent, prompt: investigate, once: true}\n",
    )

    rules = HookConfigLoader(tmp_path / "home").load(workspace).rules

    assert rules[0].condition is not None
    assert rules[0].condition.operator == "all"
    assert rules[0].condition.clauses[1].pattern.negated
    assert rules[0].action == CommandAction("check", 0.1, True, False)
    assert rules[1].action == HTTPAction(
        "https://example.com:8443/hooks",
        "PATCH",
        {"X-Test": "yes"},
        False,
        True,
    )
    assert rules[2].action == PromptAction("remember")
    assert rules[3].action == AgentAction("investigate", True)


@pytest.mark.parametrize(
    ("content", "field"),
    [
        ("unknown: true\n", "顶层"),
        ("hooks: nope\n", "hooks"),
        ("hooks:\n  - action: {type: command, command: ok}\n", "event"),
        ("hooks:\n  - event: turn_start\n", "action"),
        (
            "hooks:\n  - event: turn_start\n    extra: true\n    action: {type: command, command: ok}\n",
            "rule",
        ),
        ("hooks:\n  - event: unknown\n    action: {type: command, command: ok}\n", "event"),
        (
            "hooks:\n  - event: turn_start\n    action: {type: command, command: ''}\n",
            "action.command",
        ),
        (
            "hooks:\n  - event: turn_start\n    action: {type: command, command: ok, timeout_seconds: true}\n",
            "action.timeout_seconds",
        ),
        (
            "hooks:\n  - event: turn_start\n    action: {type: command, command: ok, timeout_seconds: 301}\n",
            "action.timeout_seconds",
        ),
        (
            "hooks:\n  - event: turn_start\n    action: {type: command, command: ok, once: yes}\n",
            "action.once",
        ),
        (
            "hooks:\n  - event: tool_before\n    action: {type: http, url: https://example.com, async: true}\n",
            "action.async",
        ),
        (
            "hooks:\n  - event: turn_start\n    action: {type: http, url: file:///tmp/hook}\n",
            "action.url",
        ),
        (
            "hooks:\n  - event: turn_start\n    action: {type: http, url: https://example.com, method: 'BAD METHOD'}\n",
            "action.method",
        ),
        (
            "hooks:\n  - event: turn_start\n    action:\n      type: http\n      url: https://example.com\n      headers: {Content-Type: text/plain}\n",
            "action.headers",
        ),
        (
            "hooks:\n  - event: session_end\n    action: {type: prompt, content: later}\n",
            "action.type",
        ),
        (
            "hooks:\n  - event: turn_start\n    action: {type: prompt, content: later, async: true}\n",
            "action",
        ),
        (
            "hooks:\n  - event: turn_start\n    if: {all: ['tool.name(run_command)']}\n    action: {type: command, command: ok}\n",
            "if",
        ),
        (
            "hooks:\n  - event: turn_start\n    if: {any: ['event(re:([)']}\n    action: {type: command, command: ok}\n",
            "if",
        ),
    ],
)
def test_invalid_rule_reports_path_index_and_field(
    tmp_path: Path,
    content: str,
    field: str,
) -> None:
    workspace = tmp_path / "workspace"
    path = workspace / ".mycode/hooks.yaml"
    write(path, content)

    with pytest.raises(ConfigError) as caught:
        HookConfigLoader(tmp_path / "home").load(workspace)

    message = caught.value.user_message
    assert str(path) in message
    assert field in message
    if content.startswith("hooks:\n  -"):
        assert "第 1 条规则" in message


@pytest.mark.parametrize(
    "content",
    [
        "hooks: []\nhooks: []\n",
        "hooks:\n  - event: turn_start\n    event: turn_end\n    action: {type: command, command: ok}\n",
        "[broken",
        "- hooks\n",
    ],
)
def test_invalid_yaml_or_duplicate_keys_are_rejected(tmp_path: Path, content: str) -> None:
    workspace = tmp_path / "workspace"
    path = workspace / ".mycode/hooks.yaml"
    write(path, content)

    with pytest.raises(ConfigError, match="Hook 配置"):
        HookConfigLoader(tmp_path / "home").load(workspace)


def test_invalid_later_layer_returns_no_partial_snapshot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    write(
        home / ".mycode/hooks.yaml",
        "hooks:\n  - event: turn_start\n    action: {type: command, command: valid}\n",
    )
    write(
        workspace / ".mycode/hooks.local.yaml",
        "hooks:\n  - event: session_end\n    action: {type: prompt, content: invalid}\n",
    )

    with pytest.raises(ConfigError) as caught:
        HookConfigLoader(home).load(workspace)

    assert str(workspace / ".mycode/hooks.local.yaml") in caught.value.user_message
