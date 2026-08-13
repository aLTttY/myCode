from __future__ import annotations

import os
import math
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlparse

import yaml

from .tools.registry import is_valid_tool_name
from .types import (
    AgentDelegationConfig,
    AppConfig,
    ConfigError,
    ContextConfig,
    HTTPMCPServerConfig,
    MCPServerConfig,
    StdioMCPServerConfig,
    ThinkingConfig,
    WorktreeConfig,
    WorktreeInitRule,
)


SUPPORTED_PROTOCOLS = {"openai", "anthropic", "deepseek"}
ENV_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
ENV_REFERENCE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
STDIO_FIELDS = {"transport", "command", "args", "env"}
HTTP_FIELDS = {"transport", "url", "headers"}
DEFAULT_TOOL_RESULT_THRESHOLD_TOKENS = 8_000
DEFAULT_TOOL_BATCH_THRESHOLD_TOKENS = 16_000
RESERVED_HTTP_HEADERS = {
    "accept",
    "content-type",
    "mcp-session-id",
    "mcp-protocol-version",
}
AGENT_CONFIG_FIELDS = {
    "model_aliases",
    "background_allowed_tools",
    "foreground_timeout_seconds",
    "task_wait_timeout_seconds",
    "task_wait_max_seconds",
    "shutdown_timeout_seconds",
    "max_concurrency",
    "max_queue_size",
    "inbox_preview_chars",
    "worktree",
}
WORKTREE_CONFIG_FIELDS = {
    "git_timeout_seconds",
    "cleanup_interval_seconds",
    "stale_after_seconds",
    "initialization",
    "copy_max_files",
    "copy_max_bytes",
}
WORKTREE_RULE_FIELDS = {"action", "source", "target", "required"}
MODEL_ALIAS_NAMES = {"haiku", "sonnet", "opus"}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def load_config(
    path: str | Path,
    *,
    user_path: str | Path | None = None,
) -> AppConfig:
    config_path = Path(path)
    resolved_user_path = (
        Path(user_path) if user_path is not None else Path.home() / ".mycode" / "config.yaml"
    )
    raw = _read_yaml(config_path, required=True, label="配置文件")
    user_raw = _read_yaml(resolved_user_path, required=False, label="用户配置")

    protocol = _required_str(raw, "protocol").lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        supported = ", ".join(sorted(SUPPORTED_PROTOCOLS))
        raise ConfigError(f"不支持的 protocol：{protocol}。支持：{supported}")

    model = _required_str(raw, "model")
    base_url = _required_str(raw, "base_url").rstrip("/")
    api_key = _resolve_api_key(_required_str(raw, "api_key"))
    thinking = _parse_thinking(raw.get("thinking"))
    mcp_servers = _merge_mcp_servers(user_raw, raw, resolved_user_path, config_path)
    context = _parse_context_config(raw)
    agents = _parse_agent_config(raw.get("agents"))

    return AppConfig(
        protocol=protocol,
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
        mcp_servers=mcp_servers,
        context=context,
        agents=agents,
    )


def _parse_agent_config(value: Any) -> AgentDelegationConfig:
    if value is None:
        return AgentDelegationConfig()
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigError("配置字段 `agents` 必须是对象。")
    unknown = sorted(set(value) - AGENT_CONFIG_FIELDS)
    if unknown:
        raise ConfigError(f"配置字段 `agents` 包含未知字段：{', '.join(unknown)}。")

    aliases_value = value.get("model_aliases", {})
    if not isinstance(aliases_value, dict) or not all(
        isinstance(key, str) for key in aliases_value
    ):
        raise ConfigError("配置字段 `agents.model_aliases` 必须是对象。")
    unknown_aliases = sorted(set(aliases_value) - MODEL_ALIAS_NAMES)
    if unknown_aliases:
        raise ConfigError(
            "配置字段 `agents.model_aliases` 包含未知档位："
            f"{', '.join(unknown_aliases)}。"
        )
    aliases: dict[str, str] = {}
    for tier, model_id in aliases_value.items():
        if not isinstance(model_id, str) or not model_id.strip():
            raise ConfigError(
                f"配置字段 `agents.model_aliases.{tier}` 必须是非空字符串。"
            )
        aliases[tier] = model_id.strip()

    defaults = AgentDelegationConfig()
    background_allowed_tools = _agent_tool_list(
        value.get("background_allowed_tools", defaults.background_allowed_tools)
    )
    foreground_timeout = _agent_positive_number(
        value,
        "foreground_timeout_seconds",
        defaults.foreground_timeout_seconds,
    )
    wait_timeout = _agent_positive_number(
        value,
        "task_wait_timeout_seconds",
        defaults.task_wait_timeout_seconds,
    )
    wait_max = _agent_positive_number(
        value,
        "task_wait_max_seconds",
        defaults.task_wait_max_seconds,
    )
    if wait_timeout > wait_max:
        raise ConfigError(
            "配置字段 `agents.task_wait_timeout_seconds` 不得大于 "
            "`agents.task_wait_max_seconds`。"
        )
    shutdown_timeout = _agent_positive_number(
        value,
        "shutdown_timeout_seconds",
        defaults.shutdown_timeout_seconds,
    )

    return AgentDelegationConfig(
        model_aliases=MappingProxyType(aliases),
        background_allowed_tools=background_allowed_tools,
        foreground_timeout_seconds=foreground_timeout,
        task_wait_timeout_seconds=wait_timeout,
        task_wait_max_seconds=wait_max,
        shutdown_timeout_seconds=shutdown_timeout,
        max_concurrency=_agent_bounded_int(
            value, "max_concurrency", defaults.max_concurrency, minimum=1, maximum=32
        ),
        max_queue_size=_agent_bounded_int(
            value, "max_queue_size", defaults.max_queue_size, minimum=0, maximum=1024
        ),
        inbox_preview_chars=_agent_bounded_int(
            value,
            "inbox_preview_chars",
            defaults.inbox_preview_chars,
            minimum=1_000,
            maximum=20_000,
        ),
        worktree=_parse_worktree_config(value.get("worktree")),
    )


def _parse_worktree_config(value: Any) -> WorktreeConfig:
    defaults = WorktreeConfig()
    if value is None:
        return defaults
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigError("配置字段 `agents.worktree` 必须是对象。")
    unknown = sorted(set(value) - WORKTREE_CONFIG_FIELDS)
    if unknown:
        raise ConfigError(
            "配置字段 `agents.worktree` 包含未知字段："
            f"{', '.join(unknown)}。"
        )
    rules_value = value.get("initialization", defaults.initialization)
    if not isinstance(rules_value, (list, tuple)):
        raise ConfigError("配置字段 `agents.worktree.initialization` 必须是规则列表。")
    rules: list[WorktreeInitRule] = []
    targets: set[str] = set()
    for index, item in enumerate(rules_value):
        prefix = f"agents.worktree.initialization[{index}]"
        if not isinstance(item, (dict, WorktreeInitRule)):
            raise ConfigError(f"配置字段 `{prefix}` 必须是对象。")
        if isinstance(item, WorktreeInitRule):
            rule = item
        else:
            if not all(isinstance(key, str) for key in item):
                raise ConfigError(f"配置字段 `{prefix}` 的字段名必须是字符串。")
            unknown_rule = sorted(set(item) - WORKTREE_RULE_FIELDS)
            if unknown_rule:
                raise ConfigError(
                    f"配置字段 `{prefix}` 包含未知字段：{', '.join(unknown_rule)}。"
                )
            action = item.get("action")
            if action not in {"copy", "symlink", "hooks"}:
                raise ConfigError(f"配置字段 `{prefix}.action` 必须是 copy、symlink 或 hooks。")
            source = item.get("source")
            if not isinstance(source, str) or not source:
                raise ConfigError(f"配置字段 `{prefix}.source` 必须是非空相对路径。")
            target = item.get("target")
            if action == "hooks":
                if target is not None:
                    raise ConfigError(f"配置字段 `{prefix}.target` 对 hooks 规则必须省略。")
            elif not isinstance(target, str) or not target:
                raise ConfigError(f"配置字段 `{prefix}.target` 对 {action} 规则必须是非空相对路径。")
            required = item.get("required", False)
            if not isinstance(required, bool):
                raise ConfigError(f"配置字段 `{prefix}.required` 必须是布尔值。")
            rule = WorktreeInitRule(action, source, target, required)
        _validate_worktree_relative_path(rule.source, f"{prefix}.source")
        if rule.target is not None:
            _validate_worktree_relative_path(rule.target, f"{prefix}.target")
            if any(
                rule.target == previous
                or rule.target.startswith(previous + "/")
                or previous.startswith(rule.target + "/")
                for previous in targets
            ):
                raise ConfigError(f"配置字段 `{prefix}.target` 与前序初始化目标冲突。")
            targets.add(rule.target)
        rules.append(rule)
    return WorktreeConfig(
        git_timeout_seconds=_nested_positive_number(
            value, "git_timeout_seconds", defaults.git_timeout_seconds
        ),
        cleanup_interval_seconds=_nested_positive_number(
            value, "cleanup_interval_seconds", defaults.cleanup_interval_seconds
        ),
        stale_after_seconds=_nested_positive_number(
            value, "stale_after_seconds", defaults.stale_after_seconds
        ),
        initialization=tuple(rules),
        copy_max_files=_nested_bounded_int(
            value, "copy_max_files", defaults.copy_max_files, 1, 1_000_000
        ),
        copy_max_bytes=_nested_bounded_int(
            value, "copy_max_bytes", defaults.copy_max_bytes, 1, 10 * 1024**3
        ),
    )


def _validate_worktree_relative_path(value: str, field: str) -> None:
    if "\\" in value:
        raise ConfigError(f"配置字段 `{field}` 不能包含反斜杠。")
    path = Path(value)
    parts = value.split("/")
    if (
        path.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or parts[:2] == [".mycode", "worktrees"]
    ):
        raise ConfigError(f"配置字段 `{field}` 必须是工作区内的安全相对路径。")


def _nested_positive_number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置字段 `agents.worktree.{key}` 必须是有限正数。")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ConfigError(f"配置字段 `agents.worktree.{key}` 必须是有限正数。")
    return number


def _nested_bounded_int(
    raw: dict[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = raw.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigError(
            f"配置字段 `agents.worktree.{key}` 必须是 {minimum}–{maximum} 之间的整数。"
        )
    return value


def _agent_tool_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) and not isinstance(value, tuple):
        raise ConfigError("配置字段 `agents.background_allowed_tools` 必须是工具名列表。")
    if not all(isinstance(item, str) and is_valid_tool_name(item) for item in value):
        raise ConfigError(
            "配置字段 `agents.background_allowed_tools` 包含非法工具名。"
        )
    if len(set(value)) != len(value):
        raise ConfigError(
            "配置字段 `agents.background_allowed_tools` 不能包含重复工具名。"
        )
    forbidden = sorted(set(value) & {"Agent", "Task", "load_skill"})
    if forbidden:
        raise ConfigError(
            "配置字段 `agents.background_allowed_tools` 不能包含子 Agent "
            f"全局禁止工具：{', '.join(forbidden)}。"
        )
    return tuple(value)


def _agent_positive_number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置字段 `agents.{key}` 必须是有限正数。")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ConfigError(f"配置字段 `agents.{key}` 必须是有限正数。")
    return number


def _agent_bounded_int(
    raw: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = raw.get(key, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigError(
            f"配置字段 `agents.{key}` 必须是 {minimum}–{maximum} 之间的整数。"
        )
    return value


def _read_yaml(
    path: Path,
    *,
    required: bool,
    label: str,
) -> dict[str, Any]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except FileNotFoundError as exc:
        if required:
            raise ConfigError(f"{label}不存在：{path}") from exc
        return {}
    except OSError as exc:
        raise ConfigError(f"无法读取{label}：{path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{label}不是有效 YAML：{path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{label}必须是 YAML 对象：{path}")
    if not all(isinstance(key, str) for key in raw):
        raise ConfigError(f"{label}的字段名必须是字符串：{path}")
    return raw


def _merge_mcp_servers(
    user_raw: dict[str, Any],
    project_raw: dict[str, Any],
    user_path: Path,
    project_path: Path,
) -> tuple[MCPServerConfig, ...]:
    user_servers = _mcp_server_map(user_raw, user_path)
    project_servers = _mcp_server_map(project_raw, project_path)
    merged = dict(user_servers)
    merged.update(project_servers)
    return tuple(
        _parse_mcp_server(name, value, project_path if name in project_servers else user_path)
        for name, value in merged.items()
    )


def _mcp_server_map(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    if "mcp_servers" not in raw:
        return {}
    value = raw["mcp_servers"]
    if not isinstance(value, dict):
        raise ConfigError(f"配置 `{path}` 的 `mcp_servers` 必须是对象。")
    if not all(isinstance(name, str) for name in value):
        raise ConfigError(f"配置 `{path}` 的 MCP Server 名必须是字符串。")
    return value


def _parse_mcp_server(name: str, value: Any, path: Path) -> MCPServerConfig:
    _validate_server_name(name, path)
    if not isinstance(value, dict):
        raise ConfigError(f"配置 `{path}` 的 MCP Server `{name}` 必须是对象。")
    if not all(isinstance(key, str) for key in value):
        raise ConfigError(f"MCP Server `{name}` 的字段名必须是字符串。")

    transport = value.get("transport")
    if transport == "stdio":
        _reject_unknown_server_fields(name, value, STDIO_FIELDS)
        command = _expanded_nonempty_string(value.get("command"), name, "command")
        args = _string_list(value.get("args", []), name, "args")
        env = _string_map(value.get("env", {}), name, "env", expand_values=True)
        return StdioMCPServerConfig(
            name=name,
            transport="stdio",
            command=command,
            args=tuple(_expand_env(item, name, "args") for item in args),
            env=env,
        )
    if transport == "http":
        _reject_unknown_server_fields(name, value, HTTP_FIELDS)
        url = _expanded_nonempty_string(value.get("url"), name, "url")
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigError(f"MCP Server `{name}` 的 `url` 必须是有效的 http 或 https URL。")
        headers = _string_map(value.get("headers", {}), name, "headers", expand_values=True)
        reserved = sorted(key for key in headers if key.lower() in RESERVED_HTTP_HEADERS)
        if reserved:
            raise ConfigError(
                f"MCP Server `{name}` 的 `headers` 包含协议保留字段：{', '.join(reserved)}。"
            )
        return HTTPMCPServerConfig(
            name=name,
            transport="http",
            url=url,
            headers=headers,
        )
    if transport is None:
        raise ConfigError(f"MCP Server `{name}` 缺少必填字段 `transport`。")
    raise ConfigError(f"MCP Server `{name}` 的 `transport` 必须是 stdio 或 http。")


def _validate_server_name(name: str, path: Path) -> None:
    if not is_valid_tool_name(name) or len(name) > 61:
        raise ConfigError(
            f"配置 `{path}` 的 MCP Server 名 `{name}` 非法；"
            "只能使用字母、数字、下划线、连字符，且长度不得超过 61。"
        )


def _reject_unknown_server_fields(
    name: str,
    value: dict[str, Any],
    allowed: set[str],
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"MCP Server `{name}` 包含未知字段：{', '.join(unknown)}。")


def _expanded_nonempty_string(value: Any, server: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"MCP Server `{server}` 的 `{field}` 必须是非空字符串。")
    expanded = _expand_env(value, server, field)
    if not expanded:
        raise ConfigError(f"MCP Server `{server}` 的 `{field}` 展开后不能为空。")
    return expanded


def _string_list(value: Any, server: str, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"MCP Server `{server}` 的 `{field}` 必须是字符串列表。")
    return value


def _string_map(
    value: Any,
    server: str,
    field: str,
    *,
    expand_values: bool,
) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key and isinstance(item, str)
        for key, item in value.items()
    ):
        raise ConfigError(f"MCP Server `{server}` 的 `{field}` 必须是非空键到字符串值的对象。")
    if not expand_values:
        return dict(value)
    return {key: _expand_env(item, server, field) for key, item in value.items()}


def _expand_env(value: str, server: str, field: str) -> str:
    def replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        if env_name not in os.environ:
            raise ConfigError(
                f"MCP Server `{server}` 的 `{field}` 引用了未设置的环境变量 `{env_name}`。"
            )
        return os.environ[env_name]

    return ENV_REFERENCE_PATTERN.sub(replace, value)


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"配置字段 `{key}` 必须是非空字符串。")
    return value.strip()


def _parse_context_config(raw: dict[str, Any]) -> ContextConfig:
    return ContextConfig(
        window_tokens=_positive_int(raw, "context_window_tokens", required=True),
        tool_result_threshold_tokens=_positive_int(
            raw,
            "tool_result_threshold_tokens",
            default=DEFAULT_TOOL_RESULT_THRESHOLD_TOKENS,
        ),
        tool_batch_threshold_tokens=_positive_int(
            raw,
            "tool_batch_threshold_tokens",
            default=DEFAULT_TOOL_BATCH_THRESHOLD_TOKENS,
        ),
    )


def _positive_int(
    raw: dict[str, Any],
    key: str,
    *,
    required: bool = False,
    default: int | None = None,
) -> int:
    if key not in raw:
        if required:
            raise ConfigError(f"配置字段 `{key}` 必须是正整数。")
        if default is None:
            raise ConfigError(f"配置字段 `{key}` 缺少默认值。")
        return default
    value = raw[key]
    if type(value) is not int or value <= 0:
        raise ConfigError(f"配置字段 `{key}` 必须是正整数。")
    return value


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
