from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from .types import AppConfig, ConfigError, ThinkingConfig


SUPPORTED_PROTOCOLS = {"openai", "anthropic", "deepseek"}
ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在：{config_path}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是有效 YAML：{config_path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("配置文件必须是 YAML 对象。")

    protocol = _required_str(raw, "protocol").lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        supported = ", ".join(sorted(SUPPORTED_PROTOCOLS))
        raise ConfigError(f"不支持的 protocol：{protocol}。支持：{supported}")

    model = _required_str(raw, "model")
    base_url = _required_str(raw, "base_url").rstrip("/")
    api_key = _resolve_api_key(_required_str(raw, "api_key"))
    thinking = _parse_thinking(raw.get("thinking"))

    return AppConfig(
        protocol=protocol,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"配置字段 `{key}` 必须是非空字符串。")
    return value.strip()


def _resolve_api_key(value: str) -> str:
    match = ENV_PATTERN.match(value)
    if match is None:
        return value

    env_name = match.group(1)
    env_value = os.environ.get(env_name)
    if not env_value:
        raise ConfigError(f"环境变量 `{env_name}` 未设置或为空。")
    return env_value


def _parse_thinking(value: Any) -> ThinkingConfig | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError("配置字段 `thinking` 必须是对象。")

    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("配置字段 `thinking.enabled` 必须是布尔值。")

    budget_tokens = value.get("budget_tokens")
    if budget_tokens is not None:
        if not isinstance(budget_tokens, int) or budget_tokens <= 0:
            raise ConfigError("配置字段 `thinking.budget_tokens` 必须是正整数。")

    return ThinkingConfig(enabled=enabled, budget_tokens=budget_tokens)
