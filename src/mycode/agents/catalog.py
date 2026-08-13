from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType

from .models import (
    AgentDefinition,
    AgentDiagnostic,
    AgentRefreshReport,
    AgentSnapshot,
    AgentSource,
)
from .parser import AgentDefinitionError, parse_agent_path, parse_agent_text


@dataclass(frozen=True)
class _Candidate:
    source: AgentSource
    source_rank: int
    source_id: str
    path: Path | None = None
    text: str | None = None


class AgentCatalog:
    def __init__(
        self,
        workspace_root: Path,
        *,
        user_agents_root: Path | None = None,
        builtin_texts: Mapping[str, str] | None = None,
        plugin_roots: Sequence[Path] = (),
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.project_agents_root = self.workspace_root / ".mycode" / "agents"
        self.user_agents_root = user_agents_root or Path.home() / ".mycode" / "agents"
        self.plugin_roots = tuple(Path(root) for root in plugin_roots)
        self._builtin_texts = dict(builtin_texts) if builtin_texts is not None else None
        self._last_state_fingerprint = ""

    def load_initial(
        self,
        known_tools: Collection[str],
        model_aliases: Mapping[str, str],
    ) -> AgentSnapshot:
        snapshot = self._build_snapshot(known_tools, model_aliases)
        self._last_state_fingerprint = self._state_fingerprint()
        return snapshot

    def refresh(
        self,
        current: AgentSnapshot,
        known_tools: Collection[str],
        model_aliases: Mapping[str, str],
    ) -> AgentRefreshReport:
        state = self._state_fingerprint()
        if state == self._last_state_fingerprint:
            return AgentRefreshReport(current, False)
        snapshot = self._build_snapshot(known_tools, model_aliases)
        self._last_state_fingerprint = state
        changed = (
            snapshot.fingerprint != current.fingerprint
            or snapshot.diagnostics != current.diagnostics
        )
        return AgentRefreshReport(snapshot if changed else current, changed)

    def _build_snapshot(
        self,
        known_tools: Collection[str],
        model_aliases: Mapping[str, str],
    ) -> AgentSnapshot:
        parsed: list[tuple[_Candidate, AgentDefinition]] = []
        diagnostics: list[AgentDiagnostic] = []
        for candidate in self._candidates():
            try:
                definition = self._parse_candidate(candidate)
            except AgentDefinitionError as exc:
                diagnostics.append(
                    AgentDiagnostic(
                        "warning", exc.code, candidate.source_id, exc.message
                    )
                )
                continue
            parsed.append((candidate, definition))

        grouped: dict[tuple[AgentSource, int, str], list[AgentDefinition]] = defaultdict(list)
        for candidate, definition in parsed:
            grouped[(candidate.source, candidate.source_rank, definition.name)].append(
                definition
            )
        invalid_groups: set[tuple[AgentSource, int, str]] = set()
        for key, definitions in grouped.items():
            if len(definitions) < 2:
                continue
            invalid_groups.add(key)
            source_ids = ", ".join(sorted(item.source_id for item in definitions))
            diagnostics.append(
                AgentDiagnostic(
                    "error",
                    "duplicate_name",
                    source_ids,
                    f"同层 Agent 角色 `{key[2]}` 重名，已回退低优先级来源。",
                )
            )

        names = sorted({definition.name for _, definition in parsed})
        selected: dict[str, AgentDefinition] = {}
        known = set(known_tools)
        source_order: list[tuple[AgentSource, int]] = [
            ("project", 0),
            ("user", 0),
            ("builtin", 0),
            *(("plugin", index) for index in range(len(self.plugin_roots))),
        ]
        for name in names:
            chosen: AgentDefinition | None = None
            chosen_level: tuple[AgentSource, int] | None = None
            for source, rank in source_order:
                key = (source, rank, name)
                if key in invalid_groups:
                    continue
                choices = grouped.get(key, ())
                if not choices:
                    continue
                candidate = choices[0]
                problem = self._semantic_problem(candidate, known, model_aliases)
                if problem is not None:
                    code, message = problem
                    diagnostics.append(
                        AgentDiagnostic("error", code, candidate.source_id, message)
                    )
                    continue
                chosen = candidate
                chosen_level = (source, rank)
                break
            if chosen is not None:
                selected[name] = chosen
                shadowed = [
                    definition
                    for (_source, _rank, candidate_name), definitions in grouped.items()
                    for definition in definitions
                    if candidate_name == name and definition.source_id != chosen.source_id
                ]
                if shadowed:
                    diagnostics.append(
                        AgentDiagnostic(
                            "warning",
                            "shadowed_definition",
                            chosen.source_id,
                            f"Agent 角色 `{name}` 采用较高优先级来源；"
                            f"已覆盖 {len(shadowed)} 个较低优先级定义。",
                        )
                    )
                if chosen_level is not None and chosen_level[0] == "plugin":
                    later = [
                        definitions[0]
                        for (source, rank, candidate_name), definitions in grouped.items()
                        if source == "plugin"
                        and rank > chosen_level[1]
                        and candidate_name == name
                        and (source, rank, candidate_name) not in invalid_groups
                    ]
                    if later:
                        diagnostics.append(
                            AgentDiagnostic(
                                "warning",
                                "plugin_override",
                                chosen.source_id,
                                f"插件 Agent 角色 `{name}` 按目录注册顺序采用首个定义。",
                            )
                        )

        fingerprint = _snapshot_fingerprint(selected)
        return AgentSnapshot(
            MappingProxyType(dict(selected)), tuple(diagnostics), fingerprint
        )

    @staticmethod
    def _semantic_problem(
        definition: AgentDefinition,
        known_tools: set[str],
        model_aliases: Mapping[str, str],
    ) -> tuple[str, str] | None:
        unknown = sorted(
            (set(definition.allowed_tools) | set(definition.denied_tools)) - known_tools
        )
        if unknown:
            return (
                "unknown_tool",
                f"Agent 角色 `{definition.name}` 声明了未知工具：{', '.join(unknown)}。",
            )
        if definition.model != "inherit" and definition.model not in model_aliases:
            return (
                "missing_model_alias",
                f"Agent 角色 `{definition.name}` 所需模型档位 `{definition.model}` 未配置。",
            )
        return None

    def _candidates(self) -> tuple[_Candidate, ...]:
        result: list[_Candidate] = []
        result.extend(self._filesystem_candidates(self.project_agents_root, "project", 0))
        result.extend(self._filesystem_candidates(self.user_agents_root, "user", 0))
        result.extend(
            _Candidate("builtin", 0, f"builtin:{name}", text=text)
            for name, text in sorted(self._builtin_resource_texts().items())
            if name.endswith(".md")
        )
        for index, root in enumerate(self.plugin_roots):
            result.extend(self._filesystem_candidates(root, "plugin", index))
        return tuple(result)

    def _filesystem_candidates(
        self, root: Path, source: AgentSource, rank: int
    ) -> list[_Candidate]:
        if not root.exists() or root.is_symlink() or not root.is_dir():
            return []
        result: list[_Candidate] = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if entry.suffix != ".md":
                continue
            if not entry.is_symlink() and not entry.is_file():
                continue
            if source == "project":
                source_id = f".mycode/agents/{entry.name}"
            elif source == "user":
                source_id = f"~/.mycode/agents/{entry.name}"
            else:
                source_id = f"plugin[{rank}]:{entry.name}"
            result.append(_Candidate(source, rank, source_id, path=entry))
        return result

    def _builtin_resource_texts(self) -> dict[str, str]:
        if self._builtin_texts is not None:
            return dict(self._builtin_texts)
        root = resources.files("mycode.agents.builtins")
        return {
            item.name: item.read_text(encoding="utf-8")
            for item in root.iterdir()
            if item.name.endswith(".md") and item.is_file()
        }

    @staticmethod
    def _parse_candidate(candidate: _Candidate) -> AgentDefinition:
        if candidate.path is not None:
            return parse_agent_path(
                candidate.path,
                source=candidate.source,
                source_id=candidate.source_id,
            )
        assert candidate.text is not None
        return parse_agent_text(
            candidate.text,
            source=candidate.source,
            source_id=candidate.source_id,
        )

    def _state_fingerprint(self) -> str:
        digest = hashlib.sha256()
        roots = [
            ("project", self.project_agents_root),
            ("user", self.user_agents_root),
            *((f"plugin:{index}", root) for index, root in enumerate(self.plugin_roots)),
        ]
        for label, root in roots:
            digest.update(label.encode("utf-8"))
            if not root.exists() or root.is_symlink() or not root.is_dir():
                digest.update(b":missing")
                continue
            for path in sorted(root.iterdir(), key=lambda item: item.name):
                try:
                    stat = path.lstat()
                except OSError:
                    continue
                digest.update(path.name.encode("utf-8"))
                digest.update(
                    f":{stat.st_mode}:{stat.st_size}:{stat.st_mtime_ns}".encode("ascii")
                )
        for name, text in sorted(self._builtin_resource_texts().items()):
            digest.update(name.encode("utf-8"))
            digest.update(text.encode("utf-8"))
        return digest.hexdigest()


def _snapshot_fingerprint(definitions: Mapping[str, AgentDefinition]) -> str:
    digest = hashlib.sha256()
    for name, definition in sorted(definitions.items()):
        digest.update(name.encode("utf-8"))
        digest.update(definition.source_id.encode("utf-8"))
        digest.update(definition.fingerprint.encode("ascii"))
    return digest.hexdigest()
