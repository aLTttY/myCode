from __future__ import annotations

import threading

from mycode.types import UserFacingError

from .models import AgentDefinition, AgentSnapshot


class AgentRoleRuntime:
    def __init__(self, snapshot: AgentSnapshot | None = None) -> None:
        self._lock = threading.RLock()
        self._snapshot = snapshot or AgentSnapshot.empty()

    @property
    def snapshot(self) -> AgentSnapshot:
        with self._lock:
            return self._snapshot

    def publish(self, snapshot: AgentSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def definition(self, name: str) -> AgentDefinition:
        with self._lock:
            try:
                return self._snapshot.definitions[name]
            except KeyError as exc:
                raise UserFacingError(f"未知或无效的 Agent 角色：{name}") from exc

    def catalog_prompt(self) -> str:
        with self._lock:
            if not self._snapshot.definitions:
                return "当前没有可用的定义式 Agent 角色。"
            rows = [
                f"- {definition.name}: {definition.description}"
                for definition in self._snapshot.definitions.values()
            ]
        return "可用的定义式 Agent 角色：\n" + "\n".join(rows)
