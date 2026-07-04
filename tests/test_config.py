from pathlib import Path

import pytest

from mycode.config import load_config
from mycode.types import ConfigError


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


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

    config = load_config(path)

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
        load_config(path)


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
        load_config(path)


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
        load_config(path)


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

    config = load_config(path)

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
        load_config(path)
