from pathlib import Path
from textwrap import indent

import pytest

from mycode.config import load_config
from mycode.types import ConfigError, HTTPMCPServerConfig, StdioMCPServerConfig


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    if "context_window_tokens:" not in content:
        content = "context_window_tokens: 200000\n" + content
    path.write_text(content, encoding="utf-8")
    return path


def load_project_config(path: Path):
    return load_config(path, user_path=path.parent / "missing-user.yaml")


def test_loads_required_fields_and_env_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "secret-value")
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: deepseek-v4-pro
base_url: https://api.deepseek.com/
api_key: ${TEST_API_KEY}
""",
    )

    config = load_project_config(path)

    assert config.protocol == "deepseek"
    assert config.model == "deepseek-v4-pro"
    assert config.base_url == "https://api.deepseek.com"
    assert config.api_key == "secret-value"
    assert config.context.window_tokens == 200_000
    assert config.context.tool_result_threshold_tokens == 8_000
    assert config.context.tool_batch_threshold_tokens == 16_000
    assert config.agents.max_concurrency == 4
    assert config.agents.max_queue_size == 32
    assert config.agents.foreground_timeout_seconds == 30.0


def test_loads_agent_delegation_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
agents:
  model_aliases:
    haiku: fast-model
    opus: strong-model
  background_allowed_tools: [read_file, search_code, custom_read]
  foreground_timeout_seconds: 12.5
  task_wait_timeout_seconds: 20
  task_wait_max_seconds: 40
  shutdown_timeout_seconds: 2
  max_concurrency: 8
  max_queue_size: 0
  inbox_preview_chars: 1000
""",
    )

    config = load_project_config(path)

    assert dict(config.agents.model_aliases) == {
        "haiku": "fast-model",
        "opus": "strong-model",
    }
    assert config.agents.background_allowed_tools == (
        "read_file",
        "search_code",
        "custom_read",
    )
    assert config.agents.foreground_timeout_seconds == 12.5
    assert config.agents.task_wait_timeout_seconds == 20.0
    assert config.agents.task_wait_max_seconds == 40.0
    assert config.agents.shutdown_timeout_seconds == 2.0
    assert config.agents.max_concurrency == 8
    assert config.agents.max_queue_size == 0
    assert config.agents.inbox_preview_chars == 1000


def test_loads_worktree_config_and_rules(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
agents:
  worktree:
    git_timeout_seconds: 2
    cleanup_interval_seconds: 3
    stale_after_seconds: 4
    copy_max_files: 5
    copy_max_bytes: 6
    initialization:
      - action: copy
        source: config.yaml
        target: config.yaml
        required: true
      - action: hooks
        source: .git/hooks
        required: false
""",
    )

    worktree = load_project_config(path).agents.worktree

    assert worktree.git_timeout_seconds == 2
    assert worktree.cleanup_interval_seconds == 3
    assert worktree.stale_after_seconds == 4
    assert worktree.initialization[0].required
    assert worktree.initialization[1].target is None


@pytest.mark.parametrize(
    "body",
    [
        "unknown: true",
        "git_timeout_seconds: false",
        "initialization: [{action: copy, source: ../secret, target: local}]",
        "initialization: [{action: hooks, source: .git/hooks, target: hooks}]",
        "initialization: [{action: copy, source: a, target: same}, {action: symlink, source: b, target: same}]",
        "initialization: [{action: copy, source: a, target: local}, {action: copy, source: b, target: local/nested}]",
        "initialization: [{action: copy, source: a, target: local/nested}, {action: copy, source: b, target: local}]",
    ],
)
def test_rejects_invalid_worktree_config(tmp_path: Path, body: str) -> None:
    path = write_config(
        tmp_path,
        f"""
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
agents:
  worktree:
    {body}
""",
    )

    with pytest.raises(ConfigError, match="worktree|initialization"):
        load_project_config(path)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("unknown: true", "未知字段"),
        ("max_concurrency: false", "max_concurrency"),
        ("max_concurrency: 33", "max_concurrency"),
        ("max_queue_size: -1", "max_queue_size"),
        ("inbox_preview_chars: 999", "inbox_preview_chars"),
        ("foreground_timeout_seconds: .inf", "foreground_timeout_seconds"),
        ("task_wait_timeout_seconds: 31\n  task_wait_max_seconds: 30", "不得大于"),
        ("background_allowed_tools: [read_file, read_file]", "重复"),
        ("background_allowed_tools: [Agent]", "全局禁止"),
        ("model_aliases: {fast: model}", "未知档位"),
    ],
)
def test_rejects_invalid_agent_delegation_config(
    tmp_path: Path, body: str, match: str
) -> None:
    path = write_config(
        tmp_path,
        f"""
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
agents:
  {body}
""",
    )

    with pytest.raises(ConfigError, match=match):
        load_project_config(path)


def test_loads_context_threshold_overrides(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
context_window_tokens: 64000
tool_result_threshold_tokens: 4000
tool_batch_threshold_tokens: 9000
""",
    )

    config = load_project_config(path)

    assert config.context.window_tokens == 64_000
    assert config.context.tool_result_threshold_tokens == 4_000
    assert config.context.tool_batch_threshold_tokens == 9_000


def test_rejects_missing_context_window(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="context_window_tokens"):
        load_project_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context_window_tokens", "false"),
        ("context_window_tokens", "0"),
        ("context_window_tokens", "-1"),
        ("context_window_tokens", '"1000"'),
        ("tool_result_threshold_tokens", "false"),
        ("tool_result_threshold_tokens", "0"),
        ("tool_batch_threshold_tokens", "-1"),
    ],
)
def test_rejects_invalid_context_token_values(tmp_path: Path, field: str, value: str) -> None:
    base_window = "" if field == "context_window_tokens" else "context_window_tokens: 64000"
    path = write_config(
        tmp_path,
        f"""
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
{base_window}
{field}: {value}
""",
    )

    with pytest.raises(ConfigError, match=field):
        load_project_config(path)


def test_rejects_missing_required_field(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: deepseek-v4-pro
base_url: https://api.deepseek.com
""",
    )

    with pytest.raises(ConfigError, match="api_key"):
        load_project_config(path)


def test_rejects_unsupported_protocol(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: unknown
model: demo
base_url: https://example.com
api_key: key
""",
    )

    with pytest.raises(ConfigError, match="不支持"):
        load_project_config(path)


def test_rejects_missing_env_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_API_KEY", raising=False)
    path = write_config(
        tmp_path,
        """
protocol: openai
model: demo
base_url: https://api.openai.com/v1
api_key: ${MISSING_API_KEY}
""",
    )

    with pytest.raises(ConfigError, match="MISSING_API_KEY"):
        load_project_config(path)


def test_loads_thinking_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: anthropic
model: claude-demo
base_url: https://api.anthropic.com
api_key: key
thinking:
  enabled: true
  budget_tokens: 4096
""",
    )

    config = load_project_config(path)

    assert config.thinking is not None
    assert config.thinking.enabled is True
    assert config.thinking.budget_tokens == 4096


def test_rejects_invalid_thinking_budget(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: anthropic
model: claude-demo
base_url: https://api.anthropic.com
api_key: key
thinking:
  enabled: true
  budget_tokens: 0
""",
    )

    with pytest.raises(ConfigError, match="budget_tokens"):
        load_project_config(path)


def test_merges_user_and_project_mcp_servers_with_project_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN", "secret-token")
    user_path = tmp_path / "user.yaml"
    user_path.write_text(
        """
mcp_servers:
  shared:
    transport: stdio
    command: user-command
  user_only:
    transport: stdio
    command: user-only
    args: ["--token=${TOKEN}"]
""",
        encoding="utf-8",
    )
    project_path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
mcp_servers:
  shared:
    transport: http
    url: https://example.com/mcp
  project_only:
    transport: stdio
    command: project-only
""",
    )

    config = load_config(project_path, user_path=user_path)

    assert [server.name for server in config.mcp_servers] == ["shared", "user_only", "project_only"]
    assert isinstance(config.mcp_servers[0], HTTPMCPServerConfig)
    assert config.mcp_servers[0].url == "https://example.com/mcp"
    assert isinstance(config.mcp_servers[1], StdioMCPServerConfig)
    assert config.mcp_servers[1].args == ("--token=secret-token",)


def test_expands_embedded_and_empty_environment_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST", "example.com")
    monkeypatch.setenv("TOKEN", "")
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
mcp_servers:
  remote:
    transport: http
    url: https://${HOST}/mcp
    headers:
      Authorization: Bearer ${TOKEN}
""",
    )

    config = load_project_config(path)
    server = config.mcp_servers[0]

    assert isinstance(server, HTTPMCPServerConfig)
    assert server.url == "https://example.com/mcp"
    assert server.headers == {"Authorization": "Bearer "}


def test_rejects_missing_mcp_environment_without_leaking_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_TOKEN", raising=False)
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
mcp_servers:
  remote:
    transport: http
    url: https://example.com/mcp
    headers:
      Authorization: Bearer known-secret-${MISSING_TOKEN}
""",
    )

    with pytest.raises(ConfigError) as caught:
        load_project_config(path)

    assert "MISSING_TOKEN" in caught.value.user_message
    assert "known-secret" not in caught.value.user_message


@pytest.mark.parametrize(
    ("server_yaml", "message"),
    [
        ("command: demo", "transport"),
        ("transport: stdio\nurl: https://example.com/mcp", "未知字段"),
        ("transport: http\ncommand: demo", "未知字段"),
        ("transport: http\nurl: ftp://example.com/mcp", "http"),
        ("transport: http\nurl: https://example.com/mcp\nheaders:\n  Accept: x", "保留字段"),
        ("transport: stdio\ncommand: demo\nargs: value", "字符串列表"),
    ],
)
def test_rejects_invalid_mcp_server_config(
    tmp_path: Path,
    server_yaml: str,
    message: str,
) -> None:
    indented = indent(server_yaml, "    ")
    path = write_config(
        tmp_path,
        f"""
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
mcp_servers:
  demo:
{indented}
""",
    )

    with pytest.raises(ConfigError, match=message):
        load_project_config(path)


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
protocol: openai
model: demo
base_url: https://example.com
api_key: key
""",
    )

    with pytest.raises(ConfigError, match="有效 YAML"):
        load_project_config(path)


def test_rejects_invalid_server_name(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
mcp_servers:
  invalid.name:
    transport: stdio
    command: demo
""",
    )

    with pytest.raises(ConfigError, match="Server 名"):
        load_project_config(path)


def test_team_config_defaults_and_two_lock_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
teams:
  max_members: 12
  verification_commands:
    - id: unit
      argv: [python, -m, pytest, -q]
      timeout_seconds: 30
  coordinator:
    enabled: true
""",
    )
    config = load_project_config(path)
    assert config.teams.max_members == 12
    assert config.teams.coordinator.enabled
    assert config.teams.verification_commands[0].command_id == "unit"


@pytest.mark.parametrize(
    "fragment",
    [
        "unknown: true",
        "max_members: 0",
        "coordinator: {enabled: 1}",
        "verification_commands: [{id: unit, argv: ['pytest; rm']}]",
    ],
)
def test_rejects_unsafe_team_config(tmp_path: Path, fragment: str) -> None:
    path = write_config(
        tmp_path,
        f"""
protocol: deepseek
model: demo
base_url: https://example.com
api_key: key
teams:
  {fragment}
""",
    )
    with pytest.raises(ConfigError):
        load_project_config(path)
