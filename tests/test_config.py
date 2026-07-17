from pathlib import Path
from textwrap import indent

import pytest

from mycode.config import load_config
from mycode.types import ConfigError, HTTPMCPServerConfig, StdioMCPServerConfig


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
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
