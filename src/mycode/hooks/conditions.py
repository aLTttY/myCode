from __future__ import annotations

import json
import re
from collections.abc import Mapping

from mycode.matching import MatchPatternError, parse_match_pattern

from .models import HookClause, HookCondition, HookEventName


_CLAUSE_PATTERN = re.compile(
    r"^(!)?([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)+)\((.+)\)$",
    re.DOTALL,
)
_COMMON_FIELDS = {
    "schema_version",
    "event",
    "occurred_at",
    "workspace",
    "session.id",
    "session.origin",
}
_TURN_FIELDS = {"turn.id", "turn.mode", "turn.input_kind"}
_EVENT_FIELDS: dict[HookEventName, set[str]] = {
    "session_start": set(),
    "session_end": {"session.end_reason"},
    "turn_start": set(_TURN_FIELDS),
    "turn_end": {*_TURN_FIELDS, "turn.stop_reason"},
    "message_received": {*_TURN_FIELDS, "message.role", "message.content"},
    "message_sent": {*_TURN_FIELDS, "message.role", "message.content"},
    "tool_before": {
        *_TURN_FIELDS,
        "tool.call_id",
        "tool.name",
    },
    "tool_after": {
        *_TURN_FIELDS,
        "tool.call_id",
        "tool.name",
        "result.ok",
        "result.message",
        "result.source",
    },
    "context_compacted": {
        *_TURN_FIELDS,
        "context.trigger",
        "context.before_tokens",
        "context.after_tokens",
        "context.budget_tokens",
        "context.offloaded_tool_results",
        "context.offloaded_user_messages",
        "context.summarized_messages",
    },
    "agent_error": {*_TURN_FIELDS, "error.code", "error.message"},
}


def parse_condition(value: object, event: HookEventName) -> HookCondition:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("if 必须是只包含 all 或 any 的对象。")
    if set(value) not in ({"all"}, {"any"}):
        raise ValueError("if 必须且只能选择 all 或 any，且不能嵌套或混用。")
    operator = next(iter(value))
    expressions = value[operator]
    if not isinstance(expressions, list) or not expressions or not all(
        isinstance(item, str) for item in expressions
    ):
        raise ValueError(f"if.{operator} 必须是非空字符串列表。")
    return HookCondition(
        operator=operator,  # type: ignore[arg-type]
        clauses=tuple(parse_clause(expression, event) for expression in expressions),
    )


def parse_clause(expression: str, event: HookEventName) -> HookClause:
    match = _CLAUSE_PATTERN.fullmatch(expression.strip())
    if match is None:
        raise ValueError(f"无效 Hook 条件：{expression!r}。应使用 字段(模式)。")
    negated_text, field, pattern_text = match.groups()
    if not field_allowed(event, field):
        raise ValueError(f"事件 `{event}` 不支持条件字段 `{field}`。")
    try:
        pattern = parse_match_pattern(pattern_text, negated=bool(negated_text))
    except MatchPatternError as exc:
        raise ValueError(str(exc)) from exc
    return HookClause(field=field, pattern=pattern)


def field_allowed(event: HookEventName, field: str) -> bool:
    if field in _COMMON_FIELDS or field in _EVENT_FIELDS[event]:
        return True
    if event in {"tool_before", "tool_after"} and field.startswith("tool.arguments."):
        return len(field.split(".")) >= 3
    if event == "tool_after" and field.startswith("result.data."):
        return len(field.split(".")) >= 3
    return False


def condition_matches(condition: HookCondition | None, payload: Mapping[str, object]) -> bool:
    if condition is None:
        return True
    matches = tuple(_clause_matches(clause, payload) for clause in condition.clauses)
    return all(matches) if condition.operator == "all" else any(matches)


def _clause_matches(clause: HookClause, payload: Mapping[str, object]) -> bool:
    found, value = _resolve(payload, clause.field)
    if not found or not _is_scalar(value):
        return False
    return clause.pattern.matches(_scalar_text(value))


def _resolve(payload: Mapping[str, object], field: str) -> tuple[bool, object]:
    current: object = payload
    for segment in field.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return False, None
        current = current[segment]
    return True, current


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
