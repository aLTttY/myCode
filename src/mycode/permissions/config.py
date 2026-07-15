from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from mycode.types import ConfigError

from .models import PermissionConfigSet, PermissionLayer, PermissionMode, RuleSource
from .rules import parse_rule


ALLOWED_FIELDS = {"mode", "allow", "deny"}
VALID_MODES = {"strict", "default", "allow"}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
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


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"无法读取权限配置 `{path}`：{exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"权限配置 `{path}` 不是有效 YAML：{exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"权限配置 `{path}` 必须是 YAML 对象。")
    if not all(isinstance(key, str) for key in raw):
        raise ConfigError(f"权限配置 `{path}` 的字段名必须是字符串。")
    return raw


def _parse_layer(path: Path, source: RuleSource, known_tools: set[str]) -> PermissionLayer:
    raw = _read_yaml(path)
    unknown = set(raw) - ALLOWED_FIELDS
    if unknown:
        raise ConfigError(f"权限配置 `{path}` 包含未知字段：{', '.join(sorted(unknown))}")
    mode = raw.get("mode")
    if mode is not None and mode not in VALID_MODES:
        raise ConfigError(f"权限配置 `{path}` 的 mode 必须是 strict、default 或 allow。")
    rules = []
    for effect in ("allow", "deny"):
        values = raw.get(effect, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ConfigError(f"权限配置 `{path}` 的 {effect} 必须是字符串列表。")
        for value in values:
            try:
                rules.append(parse_rule(value, effect, source, known_tools))
            except ValueError as exc:
                raise ConfigError(f"权限配置 `{path}`：{exc}") from exc
    return PermissionLayer(source=source, mode=mode, rules=tuple(rules))


class PermissionConfigLoader:
    def __init__(self, known_tools: set[str], user_home: Path | None = None) -> None:
        self.known_tools = set(known_tools)
        self.user_home = user_home

    def load(
        self,
        workspace_root: Path,
        cli_mode: PermissionMode | None = None,
    ) -> PermissionConfigSet:
        root = workspace_root.resolve()
        home = (self.user_home or Path.home()).expanduser()
        user = _parse_layer(home / ".mycode" / "permissions.yaml", "user", self.known_tools)
        project = _parse_layer(root / ".mycode" / "permissions.yaml", "project", self.known_tools)
        local = _parse_layer(root / ".mycode" / "permissions.local.yaml", "local", self.known_tools)
        if cli_mode is not None and cli_mode not in VALID_MODES:
            raise ConfigError("命令行权限模式必须是 strict、default 或 allow。")
        effective: PermissionMode = cli_mode or local.mode or project.mode or user.mode or "default"
        return PermissionConfigSet(user=user, project=project, local=local, effective_mode=effective)


class LocalRuleStore:
    def __init__(self, path: Path, known_tools: set[str]) -> None:
        self.path = path
        self.known_tools = set(known_tools)

    def add_exact_allow(self, tool: str, target: str) -> PermissionLayer:
        expression = f"{tool}({target})"
        try:
            parse_rule(expression, "allow", "local", self.known_tools)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        raw = _read_yaml(self.path)
        _parse_layer(self.path, "local", self.known_tools)
        allow = raw.setdefault("allow", [])
        if not isinstance(allow, list):
            raise ConfigError(f"权限配置 `{self.path}` 的 allow 必须是字符串列表。")
        if expression not in allow:
            allow.append(expression)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_name = ""
            try:
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    yaml.safe_dump(raw, temporary, allow_unicode=True, sort_keys=False)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_name = temporary.name
                os.replace(temporary_name, self.path)
            except OSError as exc:
                if temporary_name:
                    try:
                        Path(temporary_name).unlink(missing_ok=True)
                    except OSError:
                        pass
                raise ConfigError(f"无法写入本地权限配置 `{self.path}`：{exc}") from exc
        return _parse_layer(self.path, "local", self.known_tools)
