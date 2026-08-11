from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .models import (
    SkillCatalogError,
    SkillDefinition,
    SkillDiagnostic,
    SkillRefreshReport,
    SkillSnapshot,
    SkillSource,
    SkillValidationError,
    immutable_mapping,
)
from .parser import parse_skill_path, parse_skill_text


SOURCE_PRIORITY: tuple[SkillSource, ...] = ("project", "user", "builtin")


@dataclass(frozen=True)
class _Candidate:
    source: SkillSource
    source_id: str
    path: Path | None = None
    text: str | None = None
    package_root: Path | None = None


class SkillCatalog:
    def __init__(
        self,
        workspace_root: Path,
        *,
        user_skills_root: Path | None = None,
        builtin_texts: Mapping[str, str] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.project_skills_root = self.workspace_root / ".mycode" / "skills"
        self.user_skills_root = user_skills_root or (Path.home() / ".mycode" / "skills")
        self._builtin_texts = dict(builtin_texts) if builtin_texts is not None else None
        self._last_state_fingerprint = ""

    def load_initial(
        self,
        known_tools: Collection[str],
        reserved_commands: Collection[str],
    ) -> SkillSnapshot:
        snapshot = self._build_snapshot(known_tools, reserved_commands, startup=True)
        self._last_state_fingerprint = self._state_fingerprint()
        return snapshot

    def refresh(
        self,
        current: SkillSnapshot,
        known_tools: Collection[str],
        reserved_commands: Collection[str],
    ) -> SkillRefreshReport:
        state = self._state_fingerprint()
        if state == self._last_state_fingerprint:
            return SkillRefreshReport(snapshot=current, changed=False)
        snapshot = self._build_snapshot(known_tools, reserved_commands, startup=False)
        self._last_state_fingerprint = state
        changed = snapshot.fingerprint != current.fingerprint or snapshot.diagnostics != current.diagnostics
        return SkillRefreshReport(
            snapshot=snapshot if changed else current,
            changed=changed,
            diagnostics=snapshot.diagnostics,
        )

    def _build_snapshot(
        self,
        known_tools: Collection[str],
        reserved_commands: Collection[str],
        *,
        startup: bool,
    ) -> SkillSnapshot:
        parsed: list[SkillDefinition] = []
        diagnostics: list[SkillDiagnostic] = []
        for candidate in self._candidates():
            try:
                definition = self._parse_candidate(candidate)
            except SkillValidationError as exc:
                diagnostics.append(
                    SkillDiagnostic(
                        level="warning",
                        code=exc.code,
                        source_id=candidate.source_id,
                        message=exc.message,
                    )
                )
                continue
            parsed.append(definition)

        grouped: dict[tuple[SkillSource, str], list[SkillDefinition]] = defaultdict(list)
        for definition in parsed:
            grouped[(definition.source, definition.name)].append(definition)

        invalid_levels: set[tuple[SkillSource, str]] = set()
        for (source, name), definitions in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
            if len(definitions) < 2:
                continue
            sources = ", ".join(sorted(definition.source_id for definition in definitions))
            message = f"同层 Skill `{name}` 重名：{sources}。"
            if startup:
                raise SkillCatalogError(message)
            invalid_levels.add((source, name))
            diagnostics.append(SkillDiagnostic("error", "duplicate_name", sources, message))

        names = sorted({definition.name for definition in parsed})
        definitions_by_name: dict[str, SkillDefinition] = {}
        known = set(known_tools)
        reserved = {name.lower() for name in reserved_commands}
        for name in names:
            selected: SkillDefinition | None = None
            for source in SOURCE_PRIORITY:
                if (source, name) in invalid_levels:
                    continue
                choices = grouped.get((source, name), [])
                if not choices:
                    continue
                candidate = choices[0]
                problem = self._semantic_problem(candidate, known, reserved)
                if problem is None:
                    selected = candidate
                    break
                code, message = problem
                if startup:
                    raise SkillCatalogError(message)
                diagnostics.append(SkillDiagnostic("error", code, candidate.source_id, message))
            if selected is not None:
                definitions_by_name[name] = selected

        dedicated: dict[str, object] = {}
        invalid_effective: set[str] = set()
        for definition in definitions_by_name.values():
            for tool in definition.dedicated_tools:
                if tool.exposed_name in known:
                    message = (
                        f"Skill `{definition.name}` 的专属工具 `{tool.exposed_name}` "
                        "与全局工具重名。"
                    )
                    if startup:
                        raise SkillCatalogError(message)
                    diagnostics.append(
                        SkillDiagnostic("error", "dedicated_tool_conflict", definition.source_id, message)
                    )
                    invalid_effective.add(definition.name)
                    break
                dedicated[tool.exposed_name] = tool

        if invalid_effective:
            definitions_by_name = {
                name: definition
                for name, definition in definitions_by_name.items()
                if name not in invalid_effective
            }
            dedicated = {
                name: tool
                for name, tool in dedicated.items()
                if name.split("__", 1)[0] not in invalid_effective
            }

        fingerprint = _snapshot_fingerprint(definitions_by_name)
        return SkillSnapshot(
            definitions=immutable_mapping(definitions_by_name),
            dedicated_tools=immutable_mapping(dedicated),
            diagnostics=tuple(diagnostics),
            fingerprint=fingerprint,
        )

    @staticmethod
    def _semantic_problem(
        definition: SkillDefinition,
        known_tools: set[str],
        reserved_commands: set[str],
    ) -> tuple[str, str] | None:
        if definition.name in reserved_commands:
            return (
                "reserved_command",
                f"Skill `{definition.name}` 与保留斜杠命令冲突（{definition.source_id}）。",
            )
        own_tools = {tool.exposed_name for tool in definition.dedicated_tools}
        unknown = [
            name for name in definition.allowed_tools if name not in known_tools and name not in own_tools
        ]
        if unknown:
            return (
                "unknown_allowed_tool",
                f"Skill `{definition.name}` 的白名单包含未知工具：{', '.join(unknown)}。",
            )
        return None

    def _candidates(self) -> tuple[_Candidate, ...]:
        candidates: list[_Candidate] = []
        candidates.extend(self._filesystem_candidates(self.project_skills_root, "project"))
        candidates.extend(self._filesystem_candidates(self.user_skills_root, "user"))
        candidates.extend(self._builtin_candidates())
        return tuple(candidates)

    def _filesystem_candidates(self, root: Path, source: SkillSource) -> list[_Candidate]:
        if not root.exists() or root.is_symlink() or not root.is_dir():
            return []
        candidates: list[_Candidate] = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if entry.is_symlink():
                continue
            if entry.is_file() and entry.suffix == ".md":
                candidates.append(
                    _Candidate(source, self._source_id(source, root, entry), path=entry)
                )
                continue
            if entry.is_dir():
                skill_entry = entry / "SKILL.md"
                if skill_entry.is_file() and not skill_entry.is_symlink():
                    candidates.append(
                        _Candidate(
                            source,
                            self._source_id(source, root, skill_entry),
                            path=skill_entry,
                            package_root=entry,
                        )
                    )
        return candidates

    def _builtin_candidates(self) -> list[_Candidate]:
        texts = self._builtin_resource_texts()
        return [
            _Candidate("builtin", f"builtin:{name}", text=text)
            for name, text in sorted(texts.items())
            if name.endswith(".md")
        ]

    def _builtin_resource_texts(self) -> dict[str, str]:
        if self._builtin_texts is not None:
            return dict(self._builtin_texts)
        root = resources.files("mycode.skills.builtins")
        result: dict[str, str] = {}
        for item in root.iterdir():
            if item.name.endswith(".md") and item.is_file():
                result[item.name] = item.read_text(encoding="utf-8")
        return result

    @staticmethod
    def _parse_candidate(candidate: _Candidate) -> SkillDefinition:
        if candidate.path is not None:
            return parse_skill_path(
                candidate.path,
                source=candidate.source,
                source_id=candidate.source_id,
                package_root=candidate.package_root,
            )
        assert candidate.text is not None
        return parse_skill_text(
            candidate.text,
            source=candidate.source,
            source_id=candidate.source_id,
        )

    @staticmethod
    def _source_id(source: SkillSource, root: Path, path: Path) -> str:
        relative = path.relative_to(root).as_posix()
        if source == "project":
            return f".mycode/skills/{relative}"
        return f"~/.mycode/skills/{relative}"

    def _state_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for root_name, root in (
            ("project", self.project_skills_root),
            ("user", self.user_skills_root),
        ):
            digest.update(root_name.encode("utf-8"))
            if not root.exists() or root.is_symlink() or not root.is_dir():
                digest.update(b":missing")
                continue
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
                try:
                    stat = path.lstat()
                except OSError:
                    continue
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(f":{stat.st_mode}:{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        for name, text in sorted(self._builtin_resource_texts().items()):
            digest.update(name.encode("utf-8"))
            digest.update(text.encode("utf-8"))
        return digest.hexdigest()


def _snapshot_fingerprint(definitions: Mapping[str, SkillDefinition]) -> str:
    digest = hashlib.sha256()
    for name, definition in sorted(definitions.items()):
        digest.update(name.encode("utf-8"))
        digest.update(definition.source_id.encode("utf-8"))
        digest.update(definition.fingerprint.encode("ascii"))
    return digest.hexdigest()
