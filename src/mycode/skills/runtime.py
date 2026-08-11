from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from mycode.tool_safety import READ_TOOLS, SYSTEM_TOOLS
from mycode.tools.base import Tool
from mycode.tools.registry import ToolRegistry

from .models import (
    ActiveSkill,
    SkillActivation,
    SkillDefinition,
    SkillRuntimeUpdate,
    SkillSnapshot,
    SkillToolDefinition,
    SkillValidationError,
)


_SOURCE_RANK = {"project": 0, "user": 1, "builtin": 2}


class SkillRuntime:
    def __init__(
        self,
        snapshot: SkillSnapshot,
        *,
        execution_skill: SkillDefinition | None = None,
        dedicated_tool_factory: Callable[[SkillToolDefinition], Tool] | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._execution_skill = execution_skill
        self._active: list[ActiveSkill] = []
        self._next_order = 0
        self._lock = RLock()
        self._dedicated_tool_factory = dedicated_tool_factory or _default_tool_factory

    @classmethod
    def for_isolated(
        cls,
        snapshot: SkillSnapshot,
        execution_skill: SkillDefinition,
        *,
        dedicated_tool_factory: Callable[[SkillToolDefinition], Tool] | None = None,
    ) -> SkillRuntime:
        return cls(
            snapshot,
            execution_skill=execution_skill,
            dedicated_tool_factory=dedicated_tool_factory,
        )

    @property
    def snapshot(self) -> SkillSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def is_isolated(self) -> bool:
        return self._execution_skill is not None

    def definition(self, name: str) -> SkillDefinition:
        with self._lock:
            definition = self._snapshot.definitions.get(name)
        if definition is None:
            raise SkillValidationError("unknown_skill", f"未知或当前不可用的 Skill：{name}。")
        return definition

    def publish(self, snapshot: SkillSnapshot) -> SkillRuntimeUpdate:
        deactivated: list[str] = []
        replaced: list[str] = []
        with self._lock:
            old_snapshot = self._snapshot
            kept: list[ActiveSkill] = []
            for active in self._active:
                old = old_snapshot.definitions.get(active.name)
                new = snapshot.definitions.get(active.name)
                if old is None or new is None or new.mode != "shared":
                    deactivated.append(active.name)
                    continue
                same_source = old.source_id == new.source_id
                higher_override = _SOURCE_RANK[new.source] < _SOURCE_RANK[old.source]
                if not same_source and not higher_override:
                    deactivated.append(active.name)
                    continue
                if old.fingerprint != new.fingerprint or old.source_id != new.source_id:
                    replaced.append(active.name)
                kept.append(
                    ActiveSkill(
                        name=active.name,
                        activated_fingerprint=new.fingerprint,
                        order=active.order,
                    )
                )
            self._snapshot = snapshot
            self._active = kept
        return SkillRuntimeUpdate(tuple(deactivated), tuple(replaced))

    def activate_shared(self, name: str) -> SkillActivation:
        with self._lock:
            definition = self._snapshot.definitions.get(name)
            if definition is None:
                raise SkillValidationError("unknown_skill", f"未知或当前不可用的 Skill：{name}。")
            if definition.mode != "shared":
                raise SkillValidationError("not_shared", f"Skill `{name}` 不是共享模式。")
            for active in self._active:
                if active.name == name:
                    return SkillActivation(definition, newly_activated=False)
            active = ActiveSkill(name, definition.fingerprint, self._next_order)
            self._next_order += 1
            self._active.append(active)
            return SkillActivation(definition, newly_activated=True)

    def active_definitions(self) -> tuple[SkillDefinition, ...]:
        with self._lock:
            result: list[SkillDefinition] = []
            if self._execution_skill is not None:
                result.append(self._execution_skill)
            for active in sorted(self._active, key=lambda item: item.order):
                definition = self._snapshot.definitions.get(active.name)
                if definition is not None:
                    result.append(definition)
            return tuple(result)

    def active_names(self) -> tuple[str, ...]:
        return tuple(definition.name for definition in self.active_definitions())

    def catalog_prompt(self) -> str:
        active = set(self.active_names())
        with self._lock:
            definitions = tuple(self._snapshot.definitions.values())
        rows = [
            f"- `{definition.name}`：{definition.description}"
            for definition in sorted(definitions, key=lambda item: item.name)
            if definition.name not in active
        ]
        return "\n".join(rows)

    def active_prompt(self) -> tuple[str, ...]:
        return tuple(
            f"### Skill `{definition.name}`\n{definition.compiled_sop}"
            for definition in self.active_definitions()
        )

    def project_registry(self, base_registry: ToolRegistry, runtime_mode: str) -> ToolRegistry:
        active = self.active_definitions()
        allowed: set[str] | None = None
        if active:
            allowed = {
                name
                for definition in active
                for name in definition.allowed_tools
            }
        if runtime_mode == "plan":
            allowed = set(READ_TOOLS) if allowed is None else allowed & set(READ_TOOLS)

        registry = ToolRegistry()
        for name in base_registry.names():
            if name in SYSTEM_TOOLS:
                continue
            if allowed is None or name in allowed:
                registry.register(base_registry.get(name))

        if active and runtime_mode != "plan":
            for definition in active:
                for tool in definition.dedicated_tools:
                    if tool.exposed_name in definition.allowed_tools and not registry.contains(tool.exposed_name):
                        registry.register(self._dedicated_tool_factory(tool))

        for name in SYSTEM_TOOLS:
            if base_registry.contains(name) and not registry.contains(name):
                registry.register(base_registry.get(name))
        return registry

    def reset(self) -> None:
        with self._lock:
            self._active = []
            self._next_order = 0


def _default_tool_factory(definition: SkillToolDefinition) -> Tool:
    from .tools import SkillScriptTool

    return SkillScriptTool(definition)
