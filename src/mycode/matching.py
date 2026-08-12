from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Literal


MatchKind = Literal["exact", "regex", "glob"]

_GLOB_PATTERN = re.compile(r"[*?[]")
_MATCH_KIND_PRIORITY: dict[MatchKind, int] = {
    "exact": 3,
    "regex": 2,
    "glob": 1,
}


class MatchPatternError(ValueError):
    pass


@dataclass(frozen=True)
class MatchPattern:
    kind: MatchKind
    value: str
    negated: bool = False
    _compiled: re.Pattern[str] | None = field(default=None, repr=False, compare=False)

    @property
    def priority(self) -> int:
        return _MATCH_KIND_PRIORITY[self.kind]

    def matches(self, candidate: str) -> bool:
        if self.kind == "exact":
            matched = candidate == self.value
        elif self.kind == "glob":
            matched = fnmatch.fnmatchcase(candidate, self.value)
        else:
            compiled = self._compiled or re.compile(self.value)
            matched = compiled.search(candidate) is not None
        return not matched if self.negated else matched

    def render(self) -> str:
        if self.kind == "regex":
            body = f"re:{self.value}"
        elif self.kind == "glob" and not _GLOB_PATTERN.search(self.value):
            body = f"glob:{self.value}"
        else:
            body = self.value
        return body


def parse_match_pattern(value: str, *, negated: bool = False) -> MatchPattern:
    if not isinstance(value, str) or not value:
        raise MatchPatternError("匹配模式必须是非空字符串。")

    if value.startswith("re:"):
        pattern = value[3:]
        if not pattern:
            raise MatchPatternError("正则匹配模式不能为空。")
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise MatchPatternError(f"无效正则表达式：{exc.msg}。") from exc
        return MatchPattern("regex", pattern, negated, compiled)

    if value.startswith("glob:"):
        pattern = value[5:]
        if not pattern:
            raise MatchPatternError("glob 匹配模式不能为空。")
        return MatchPattern("glob", pattern, negated)

    kind: MatchKind = "glob" if _GLOB_PATTERN.search(value) else "exact"
    return MatchPattern(kind, value, negated)
