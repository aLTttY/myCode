from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from mycode.context.models import CompactionReport
from mycode.prompts.modes import DynamicInstruction
from mycode.types import ToolCall, ToolExecutionResult

from .actions import HookActionExecutor
from .conditions import condition_matches
from .events import HookEventFactory
from .models import (
    HookActionOutcome,
    HookDiagnostic,
    HookDispatchResult,
    HookEvent,
    HookPromptLease,
    HookResultSource,
    HookRule,
    HookSnapshot,
    HookTurn,
    PromptAction,
)


DiagnosticSink = Callable[[HookDiagnostic], None]
_MAX_DIAGNOSTIC_CHARS = 2_000


@dataclass(frozen=True)
class _QueuedPrompt:
    instruction: DynamicInstruction


@dataclass(frozen=True)
class _ActiveLease:
    lease_id: str
    count: int


class HookRuntime:
    def __init__(
        self,
        snapshot: HookSnapshot,
        event_factory: HookEventFactory,
        action_executor: HookActionExecutor | None = None,
        diagnostic_sink: DiagnosticSink | None = None,
        *,
        _shared_once: tuple[set[str], set[str], threading.RLock] | None = None,
        _owns_action_executor: bool = True,
    ) -> None:
        self.snapshot = snapshot
        self.events = event_factory
        self.action_executor = action_executor
        self._diagnostic_sink = diagnostic_sink or (lambda diagnostic: None)
        if _shared_once is None:
            self._consumed_once = set()
            self._in_flight_once = set()
            self._lock = threading.RLock()
            self._owns_once_state = True
        else:
            self._consumed_once, self._in_flight_once, self._lock = _shared_once
            self._owns_once_state = False
        self._prompts: list[_QueuedPrompt] = []
        self._active_lease: _ActiveLease | None = None
        self._prompt_sequence = 0
        self._lease_sequence = 0
        self._turn_sequence = 0
        self._session_active = False
        self._closed = False
        self._owns_action_executor = _owns_action_executor

    def fork_scope(
        self,
        session_id: str,
        scope_id: str,
        *,
        kind: str,
        role: str = "",
    ) -> "HookRuntime":
        events = HookEventFactory(self.events.workspace_root, clock=self.events.clock)
        events.set_agent_scope(kind, task_id=scope_id, role=role)
        scope = HookRuntime(
            self.snapshot,
            events,
            self.action_executor,
            self._diagnostic_sink,
            _shared_once=(self._consumed_once, self._in_flight_once, self._lock),
            _owns_action_executor=False,
        )
        scope.begin_session(session_id, kind)
        return scope

    def begin_session(self, session_id: str, origin: str) -> None:
        with self._lock:
            if self._closed:
                return
            if self._owns_once_state:
                self._consumed_once.clear()
                self._in_flight_once.clear()
            self._prompts.clear()
            self._active_lease = None
            self._prompt_sequence = 0
            self._lease_sequence = 0
            self._turn_sequence = 0
            self.events.set_turn(None)
            self.events.set_session(session_id, origin)
            self._session_active = True
        self._dispatch(self.events.build("session_start"))

    def end_session(self, reason: str) -> None:
        with self._lock:
            if self._closed or not self._session_active:
                return
            self._session_active = False
        self._dispatch(self.events.build("session_end", end_reason=reason))

    def begin_turn(self, mode: str, input_kind: str) -> int:
        with self._lock:
            if self._closed:
                return 0
            self._turn_sequence += 1
            turn = HookTurn(self._turn_sequence, mode, input_kind)
            self.events.set_turn(turn)
        self._dispatch(self.events.build("turn_start"))
        return turn.id

    def end_turn(self, stop_reason: str) -> None:
        with self._lock:
            if self._closed or self.events.turn is None:
                return
        try:
            self._dispatch(self.events.build("turn_end", stop_reason=stop_reason))
        finally:
            with self._lock:
                self.events.set_turn(None)

    def message_received(self, content: str) -> None:
        self._dispatch(
            self.events.build(
                "message_received",
                message_role="user",
                message_content=content,
            )
        )

    def message_sent(self, content: str) -> None:
        self._dispatch(
            self.events.build(
                "message_sent",
                message_role="assistant",
                message_content=content,
            )
        )

    def before_tool(self, call: ToolCall) -> HookDispatchResult:
        return self._dispatch(self.events.build("tool_before", tool_call=call))

    def after_tool(
        self,
        call: ToolCall,
        result: ToolExecutionResult,
        source: HookResultSource,
    ) -> None:
        self._dispatch(
            self.events.build(
                "tool_after",
                tool_call=call,
                tool_result=result,
                result_source=source,
            )
        )

    def context_compacted(self, report: CompactionReport) -> None:
        if report.status != "success":
            return
        self._dispatch(self.events.build("context_compacted", context_report=report))

    def agent_error(self, code: str, message: str) -> None:
        self._dispatch(
            self.events.build("agent_error", error_code=code, error_message=message)
        )

    def reserve_prompts(self) -> HookPromptLease:
        with self._lock:
            if self._active_lease is not None:
                return self._lease_value(self._active_lease)
            self._lease_sequence += 1
            lease = _ActiveLease(f"hook-prompt-lease-{self._lease_sequence}", len(self._prompts))
            self._active_lease = lease
            return self._lease_value(lease)

    def refresh_prompt_lease(self, lease_id: str) -> HookPromptLease:
        with self._lock:
            lease = self._require_lease(lease_id)
            refreshed = _ActiveLease(lease.lease_id, len(self._prompts))
            self._active_lease = refreshed
            return self._lease_value(refreshed)

    def commit_prompt_lease(self, lease_id: str) -> None:
        with self._lock:
            lease = self._require_lease(lease_id)
            del self._prompts[: lease.count]
            self._active_lease = None

    def release_prompt_lease(self, lease_id: str) -> None:
        with self._lock:
            self._require_lease(lease_id)
            self._active_lease = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._owns_action_executor and self.action_executor is not None:
            try:
                self.action_executor.close()
            except Exception:  # noqa: BLE001 - Hook 清理不得影响宿主退出。
                pass

    def _dispatch(self, event: HookEvent) -> HookDispatchResult:
        with self._lock:
            if self._closed:
                return HookDispatchResult()
        for rule in self.snapshot.rules:
            if rule.event != event.name or not self._claim(rule):
                continue
            try:
                if not condition_matches(rule.condition, event.payload):
                    self._release_claim(rule, consume=False)
                    continue
            except Exception:  # noqa: BLE001 - 运行期匹配故障必须 fail-open。
                self._release_claim(rule, consume=False)
                self._diagnose(rule, event, "condition_error", "Hook 条件判断失败。")
                continue

            outcome = self._run_rule(rule, event)
            self._release_claim(rule, consume=_consumes_once(outcome))
            if outcome.status in {"failed", "cancelled", "placeholder"}:
                self._diagnose(rule, event, outcome.code or outcome.status, outcome.reason)
            if event.name == "tool_before" and outcome.status == "denied":
                return HookDispatchResult(denied=True, reason=outcome.reason)
        return HookDispatchResult()

    def _claim(self, rule: HookRule) -> bool:
        if not getattr(rule.action, "once", False):
            return True
        with self._lock:
            if rule.rule_id in self._consumed_once or rule.rule_id in self._in_flight_once:
                return False
            self._in_flight_once.add(rule.rule_id)
            return True

    def _release_claim(self, rule: HookRule, *, consume: bool) -> None:
        if not getattr(rule.action, "once", False):
            return
        with self._lock:
            self._in_flight_once.discard(rule.rule_id)
            if consume:
                self._consumed_once.add(rule.rule_id)

    def _run_rule(self, rule: HookRule, event: HookEvent) -> HookActionOutcome:
        if isinstance(rule.action, PromptAction):
            with self._lock:
                self._prompt_sequence += 1
                instruction = DynamicInstruction(
                    tag=f"mewcode_hook_prompt_{self._prompt_sequence}",
                    content=rule.action.content,
                    full=True,
                )
                self._prompts.append(_QueuedPrompt(instruction))
            return HookActionOutcome("success", code="prompt_queued")
        if self.action_executor is None:
            return HookActionOutcome(
                "failed",
                "Hook 外部动作执行器不可用。",
                "action_executor_unavailable",
            )
        try:
            return self.action_executor.execute(
                rule.action,
                event,
                callback=lambda outcome: self._async_outcome(rule, event, outcome),
            )
        except Exception:  # noqa: BLE001 - 动作实现不得穿透 Runtime。
            return HookActionOutcome("failed", "Hook 动作执行失败。", "action_error")

    def _async_outcome(
        self,
        rule: HookRule,
        event: HookEvent,
        outcome: HookActionOutcome,
    ) -> None:
        if outcome.status in {"failed", "cancelled", "placeholder"}:
            self._diagnose(rule, event, outcome.code or outcome.status, outcome.reason)

    def _diagnose(
        self,
        rule: HookRule,
        event: HookEvent,
        code: str,
        message: str,
    ) -> None:
        safe_message = (message or "Hook 动作未成功。")[:_MAX_DIAGNOSTIC_CHARS]
        diagnostic = HookDiagnostic(
            source_path=rule.source_path,
            source_index=rule.source_index,
            event=event.name,
            code=code[:100],
            message=safe_message,
        )
        try:
            self._diagnostic_sink(diagnostic)
        except Exception:  # noqa: BLE001 - 日志 sink 不得影响 Agent。
            pass

    def _lease_value(self, lease: _ActiveLease) -> HookPromptLease:
        return HookPromptLease(
            lease_id=lease.lease_id,
            instructions=tuple(item.instruction for item in self._prompts[: lease.count]),
        )

    def _require_lease(self, lease_id: str) -> _ActiveLease:
        lease = self._active_lease
        if lease is None or lease.lease_id != lease_id:
            raise ValueError("Hook prompt lease 不存在或已失效。")
        return lease


def _consumes_once(outcome: HookActionOutcome) -> bool:
    return outcome.status in {"success", "submitted", "denied", "placeholder"}
