from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Sequence

from .models import (
    MatchType,
    PermissionDecision,
    PermissionLayer,
    PermissionRequest,
    PermissionRule,
    RuleEffect,
    RuleSource,
)


RULE_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\((.+)\)$", re.DOTALL)
GLOB_PATTERN = re.compile(r"[*?[]")


def parse_rule(
    expression: str,
    effect: RuleEffect,
    source: RuleSource,
    known_tools: Iterable[str],
) -> PermissionRule:
    if not isinstance(expression, str):
        raise ValueError("权限规则必须是字符串。")
    match = RULE_PATTERN.fullmatch(expression.strip())
    if match is None:
        raise ValueError(f"无效权限规则：{expression!r}。应使用 工具名(模式)。")
    tool, pattern = match.groups()
    if tool not in set(known_tools):
        raise ValueError(f"权限规则引用未知工具：{tool}")
    match_type: MatchType = "glob" if GLOB_PATTERN.search(pattern) else "exact"
    return PermissionRule(tool=tool, pattern=pattern, effect=effect, source=source, match_type=match_type)


def rule_matches(rule: PermissionRule, request: PermissionRequest) -> bool:
    if rule.tool != request.tool:
        return False
    if rule.match_type == "exact":
        return rule.pattern == request.target
    return fnmatch.fnmatchcase(request.target, rule.pattern)


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
            exact = [rule for rule in matches if rule.match_type == "exact"]
            candidates = exact or matches
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
