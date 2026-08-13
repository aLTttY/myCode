from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from mycode.tools.registry import is_valid_tool_name

from .models import AgentDefinition, AgentSource


REQUIRED_FIELDS = frozenset(
    {
        "name",
        "description",
        "allowed_tools",
        "denied_tools",
        "model",
        "max_iterations",
        "permission_mode",
    }
)
OPTIONAL_FIELDS = frozenset({"isolation"})
MODEL_TIERS = frozenset({"inherit", "haiku", "sonnet", "opus"})
PERMISSION_MODES = frozenset({"inherit", "default", "strict"})
GLOBAL_CHILD_DENY = frozenset({"Agent", "Task", "load_skill"})
ROLE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class AgentDefinitionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def parse_agent_path(
    path: Path,
    *,
    source: AgentSource,
    source_id: str,
) -> AgentDefinition:
    if path.is_symlink():
        raise AgentDefinitionError("symlink_entry", "Agent 定义入口不能是符号链接。")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AgentDefinitionError(
            "entry_read_failed",
            f"无法读取 Agent 定义（{type(exc).__name__}）。",
        ) from exc
    return parse_agent_text(text, source=source, source_id=source_id)


def parse_agent_text(
    text: str,
    *,
    source: AgentSource,
    source_id: str,
) -> AgentDefinition:
    metadata, prompt = _split_frontmatter(text)
    missing = REQUIRED_FIELDS - set(metadata)
    unknown = set(metadata) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    if missing:
        raise AgentDefinitionError(
            "missing_field", f"缺少必填字段：{', '.join(sorted(missing))}。"
        )
    if unknown:
        raise AgentDefinitionError(
            "unknown_field", f"存在未知字段：{', '.join(sorted(unknown))}。"
        )

    name = _strict_string(metadata, "name")
    if ROLE_NAME_PATTERN.fullmatch(name) is None:
        raise AgentDefinitionError("invalid_name", "Agent 角色名必须是安全的小写名称。")
    description = _strict_string(metadata, "description")
    if "\n" in description or "\r" in description:
        raise AgentDefinitionError("invalid_description", "Agent 用途说明必须是单行文本。")

    allowed = _tool_list(metadata, "allowed_tools")
    denied = _tool_list(metadata, "denied_tools")
    overlap = sorted(set(allowed) & set(denied))
    if overlap:
        raise AgentDefinitionError(
            "tool_list_overlap",
            f"工具白名单与黑名单不能相交：{', '.join(overlap)}。",
        )
    forbidden = sorted((set(allowed) | set(denied)) & GLOBAL_CHILD_DENY)
    if forbidden:
        raise AgentDefinitionError(
            "globally_forbidden_tool",
            f"角色不能声明全局禁止工具：{', '.join(forbidden)}。",
        )

    model = metadata.get("model")
    if model not in MODEL_TIERS:
        raise AgentDefinitionError(
            "invalid_model", "model 必须是 inherit、haiku、sonnet 或 opus。"
        )
    max_iterations = metadata.get("max_iterations")
    if type(max_iterations) is not int or not 1 <= max_iterations <= 64:
        raise AgentDefinitionError(
            "invalid_max_iterations", "max_iterations 必须是 1–64 之间的整数。"
        )
    permission_mode = metadata.get("permission_mode")
    if permission_mode not in PERMISSION_MODES:
        raise AgentDefinitionError(
            "invalid_permission_mode",
            "permission_mode 必须是 inherit、default 或 strict。",
        )
    isolation = metadata.get("isolation", "shared")
    if "isolation" in metadata and isolation != "worktree":
        raise AgentDefinitionError(
            "invalid_isolation", "isolation 省略时为 shared，显式值只能是 worktree。"
        )

    return AgentDefinition(
        name=name,
        description=description,
        allowed_tools=allowed,
        denied_tools=denied,
        model=model,
        max_iterations=max_iterations,
        permission_mode=permission_mode,
        isolation=isolation,
        system_prompt=prompt,
        source=source,
        source_id=source_id,
        fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def _split_frontmatter(text: str) -> tuple[Mapping[str, object], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentDefinitionError(
            "missing_frontmatter", "Agent 定义必须以 YAML frontmatter 开始。"
        )
    closing = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if closing is None:
        raise AgentDefinitionError(
            "unclosed_frontmatter", "Agent frontmatter 缺少结束标记。"
        )
    try:
        loaded = yaml.load("\n".join(lines[1:closing]), Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise AgentDefinitionError(
            "invalid_yaml", "Agent frontmatter 不是合法 YAML。"
        ) from exc
    if not isinstance(loaded, Mapping) or not all(isinstance(key, str) for key in loaded):
        raise AgentDefinitionError(
            "invalid_frontmatter", "Agent frontmatter 必须是字符串字段映射。"
        )
    prompt = "\n".join(lines[closing + 1 :]).strip()
    if not prompt:
        raise AgentDefinitionError("empty_prompt", "Agent 系统提示不能为空。")
    return loaded, prompt


def _strict_string(values: Mapping[str, object], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AgentDefinitionError(
            f"invalid_{field}", f"字段 {field} 必须是无外围空白的非空字符串。"
        )
    return value


def _tool_list(values: Mapping[str, object], field: str) -> tuple[str, ...]:
    value = values.get(field)
    if not isinstance(value, list):
        raise AgentDefinitionError(f"invalid_{field}", f"字段 {field} 必须是列表。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or item != item.strip() or not is_valid_tool_name(item):
            raise AgentDefinitionError(
                f"invalid_{field}", f"字段 {field} 包含非法工具名。"
            )
        if item in result:
            raise AgentDefinitionError(
                f"duplicate_{field}", f"字段 {field} 不能包含重复工具名。"
            )
        result.append(item)
    return tuple(result)
