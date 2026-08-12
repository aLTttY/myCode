from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from mycode.matching import MatchPatternError, parse_match_pattern
from mycode.tools.registry import is_valid_tool_name

from .models import (
    PermissionDecision,
    PermissionLayer,
    PermissionRequest,
    PermissionRule,
    RuleEffect,
    RuleSource,
)


RULE_PATTERN = re.compile(r"^(!)?([A-Za-z0-9_-]{1,64})\((.+)\)$", re.DOTALL)


def parse_rule(
    expression: str,
    effect: RuleEffect,
    source: RuleSource,
    known_tools: Iterable[str],
    allowed_tool_prefixes: Iterable[str] = (),
) -> PermissionRule:
    if not isinstance(expression, str):
        raise ValueError("权限规则必须是字符串。")
    match = RULE_PATTERN.fullmatch(expression.strip())
    if match is None:
        raise ValueError(f"无效权限规则：{expression!r}。应使用 工具名(模式)。")
    negated_text, tool, pattern = match.groups()
    prefixes = tuple(allowed_tool_prefixes)
    known = tool in set(known_tools)
    allowed_dynamic = is_valid_tool_name(tool) and any(
        tool.startswith(prefix) and len(tool) > len(prefix)
        for prefix in prefixes
    )
    if not known and not allowed_dynamic:
        raise ValueError(f"权限规则引用未知工具：{tool}")
    try:
        matcher = parse_match_pattern(pattern, negated=bool(negated_text))
    except MatchPatternError as exc:
        raise ValueError(str(exc)) from exc
    return PermissionRule(tool=tool, matcher=matcher, effect=effect, source=source)


def rule_matches(rule: PermissionRule, request: PermissionRequest) -> bool:
    if rule.tool != request.tool:
        return False
    return rule.matcher.matches(request.target)


class RuleEngine:
    def decide(
        self,
        request: PermissionRequest,
        layers: Sequence[PermissionLayer],
    ) -> PermissionDecision | None:
        for layer in layers:
            matches = [rule for rule in layer.rules if rule_matches(rule, request)]
            if not matches:
                continue
            highest_priority = max(rule.matcher.priority for rule in matches)
            candidates = [
                rule for rule in matches if rule.matcher.priority == highest_priority
            ]
            denied = [rule for rule in candidates if rule.effect == "deny"]
            selected = denied[0] if denied else candidates[0]
            allowed = selected.effect == "allow"
            return PermissionDecision(
                allowed=allowed,
                reason_code="rule_allow" if allowed else "rule_deny",
                message=(
                    f"{layer.source} 层权限规则允许此调用。"
                    if allowed
                    else f"{layer.source} 层权限规则拒绝此调用。"
                ),
                target=request.target,
                matched_source=layer.source,
                matched_rule=selected,
            )
        return None
