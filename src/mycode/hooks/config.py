from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, cast
from urllib.parse import urlsplit

import yaml

from mycode.types import ConfigError

from .conditions import parse_condition
from .models import (
    HOOK_EVENT_NAMES,
    AgentAction,
    CommandAction,
    FrozenDict,
    HookAction,
    HookEventName,
    HookRule,
    HookSnapshot,
    HookSource,
    HTTPAction,
    PromptAction,
)


_TOP_LEVEL_FIELDS = {"hooks"}
_RULE_FIELDS = {"event", "if", "action"}
_ACTION_FIELDS: dict[str, set[str]] = {
    "command": {"type", "command", "timeout_seconds", "once", "async"},
    "http": {"type", "url", "method", "headers", "once", "async"},
    "prompt": {"type", "content", "once"},
    "agent": {"type", "prompt", "once"},
}
_HTTP_METHOD = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


# Hook 配置按 YAML 1.2 的布尔语义处理，避免 `yes`/`no` 被悄悄转换成布尔值。
_UniqueKeyLoader.yaml_implicit_resolvers = {
    key: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_UniqueKeyLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _construct_mapping(
    loader: _UniqueKeyLoader,
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


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"无法读取 Hook 配置 `{path}`：{exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Hook 配置 `{path}` 不是有效 YAML：{exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Hook 配置 `{path}` 顶层必须是 YAML 对象。")
    if not all(isinstance(key, str) for key in raw):
        raise ConfigError(f"Hook 配置 `{path}` 顶层字段名必须是字符串。")
    unknown = set(raw) - _TOP_LEVEL_FIELDS
    if unknown:
        raise ConfigError(
            f"Hook 配置 `{path}` 顶层包含未知字段：{', '.join(sorted(unknown))}。"
        )
    return cast(dict[str, Any], raw)


def _rule_error(path: Path, index: int, field: str, message: str) -> ConfigError:
    return ConfigError(f"Hook 配置 `{path}` 第 {index} 条规则的 `{field}`：{message}")


def _require_string(
    action: Mapping[str, object],
    name: str,
    path: Path,
    index: int,
) -> str:
    value = action.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _rule_error(path, index, f"action.{name}", "必须是非空字符串。")
    return value


def _boolean(
    action: Mapping[str, object],
    name: str,
    path: Path,
    index: int,
    *,
    default: bool = False,
) -> bool:
    value = action.get(name, default)
    if not isinstance(value, bool):
        raise _rule_error(path, index, f"action.{name}", "必须是布尔值。")
    return value


def _parse_headers(value: object, path: Path, index: int) -> Mapping[str, str]:
    if value is None:
        return FrozenDict()
    if not isinstance(value, dict):
        raise _rule_error(path, index, "action.headers", "必须是字符串到字符串的对象。")
    headers: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(item, str):
            raise _rule_error(
                path,
                index,
                "action.headers",
                "header 名必须是非空字符串，值必须是字符串。",
            )
        if key.lower() == "content-type":
            raise _rule_error(
                path,
                index,
                "action.headers",
                "Content-Type 由 Hook 固定为 application/json，不能配置。",
            )
        headers[key] = item
    return FrozenDict(headers)


def _parse_action(
    raw: object,
    event: HookEventName,
    path: Path,
    index: int,
) -> HookAction:
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise _rule_error(path, index, "action", "必须是字段名为字符串的对象。")
    action = cast(dict[str, object], raw)
    action_type = action.get("type")
    if not isinstance(action_type, str) or action_type not in _ACTION_FIELDS:
        raise _rule_error(
            path,
            index,
            "action.type",
            "必须是 command、http、prompt 或 agent。",
        )
    unknown = set(action) - _ACTION_FIELDS[action_type]
    if unknown:
        raise _rule_error(
            path,
            index,
            "action",
            f"包含不适用于 {action_type} 的字段：{', '.join(sorted(unknown))}。",
        )

    once = _boolean(action, "once", path, index)
    asynchronous = False
    if action_type in {"command", "http"}:
        asynchronous = _boolean(action, "async", path, index)
        if event == "tool_before" and asynchronous:
            raise _rule_error(path, index, "action.async", "tool_before 动作不允许异步。")

    if action_type == "command":
        command = _require_string(action, "command", path, index)
        timeout = action.get("timeout_seconds", 10.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise _rule_error(path, index, "action.timeout_seconds", "必须是数字。")
        timeout_seconds = float(timeout)
        if not 0.1 <= timeout_seconds <= 300:
            raise _rule_error(
                path,
                index,
                "action.timeout_seconds",
                "必须在 0.1 到 300 秒之间。",
            )
        return CommandAction(
            command=command,
            timeout_seconds=timeout_seconds,
            once=once,
            asynchronous=asynchronous,
        )

    if action_type == "http":
        url = _require_string(action, "url", path, index)
        parsed_url = urlsplit(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise _rule_error(path, index, "action.url", "必须是有效的 http 或 https URL。")
        try:
            if parsed_url.port is not None and not 1 <= parsed_url.port <= 65535:
                raise ValueError
        except ValueError as exc:
            raise _rule_error(path, index, "action.url", "包含无效端口。") from exc
        method = action.get("method", "POST")
        if not isinstance(method, str) or not _HTTP_METHOD.fullmatch(method):
            raise _rule_error(path, index, "action.method", "必须是合法的 HTTP 方法标记。")
        return HTTPAction(
            url=url,
            method=method.upper(),
            headers=_parse_headers(action.get("headers"), path, index),
            once=once,
            asynchronous=asynchronous,
        )

    if action_type == "prompt":
        if event == "session_end":
            raise _rule_error(path, index, "action.type", "session_end 不允许 prompt 动作。")
        return PromptAction(content=_require_string(action, "content", path, index), once=once)

    return AgentAction(prompt=_require_string(action, "prompt", path, index), once=once)


def _parse_layer(path: Path, source: HookSource) -> tuple[HookRule, ...]:
    raw = _read_yaml(path)
    hooks = raw.get("hooks", [])
    if not isinstance(hooks, list):
        raise ConfigError(f"Hook 配置 `{path}` 的 `hooks` 必须是规则列表。")
    rules: list[HookRule] = []
    for index, item in enumerate(hooks, start=1):
        if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
            raise _rule_error(path, index, "rule", "必须是字段名为字符串的对象。")
        raw_rule = cast(dict[str, object], item)
        unknown = set(raw_rule) - _RULE_FIELDS
        if unknown:
            raise _rule_error(
                path,
                index,
                "rule",
                f"包含未知字段：{', '.join(sorted(unknown))}。",
            )
        if "event" not in raw_rule:
            raise _rule_error(path, index, "event", "缺少必填字段。")
        if "action" not in raw_rule:
            raise _rule_error(path, index, "action", "缺少必填字段。")
        event_value = raw_rule["event"]
        if not isinstance(event_value, str) or event_value not in HOOK_EVENT_NAMES:
            raise _rule_error(path, index, "event", "不是受支持的生命周期事件。")
        event = cast(HookEventName, event_value)
        condition = None
        if "if" in raw_rule:
            try:
                condition = parse_condition(raw_rule["if"], event)
            except ValueError as exc:
                raise _rule_error(path, index, "if", str(exc)) from exc
        action = _parse_action(raw_rule["action"], event, path, index)
        rules.append(
            HookRule(
                rule_id=f"{source}:{index}",
                source=source,
                source_path=path,
                source_index=index,
                event=event,
                condition=condition,
                action=action,
            )
        )
    return tuple(rules)


class HookConfigLoader:
    def __init__(self, user_home: Path | None = None) -> None:
        self.user_home = user_home

    def load(self, workspace_root: Path) -> HookSnapshot:
        root = workspace_root.resolve()
        home = (self.user_home or Path.home()).expanduser()
        rules: list[HookRule] = []
        for path, source in (
            (home / ".mycode" / "hooks.yaml", "user"),
            (root / ".mycode" / "hooks.yaml", "project"),
            (root / ".mycode" / "hooks.local.yaml", "local"),
        ):
            rules.extend(_parse_layer(path, cast(HookSource, source)))
        return HookSnapshot(rules=tuple(rules))
