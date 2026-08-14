from __future__ import annotations

import asyncio
import inspect
import secrets
import threading
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Callable

from mycode.teams.models import MemberProcessIdentity, TeamMemberSnapshot

from .base import (
    BackendProbeRequest,
    BackendProbeResult,
    BackendStartResult,
    BackendStatus,
    BackendWakeResult,
    MemberStopResult,
)


class CoroutineBackend:
    name = "coroutine"

    def __init__(
        self,
        runner: Callable[[TeamMemberSnapshot, threading.Event, threading.Event], object] | None = None,
        *,
        defer_start: bool = False,
    ) -> None:
        self.runner = runner or (lambda _member, cancel, wake: None)
        self.defer_start = defer_start
        self._executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="mycode-team")
        self._runs: dict[str, tuple[Future[object], threading.Event, threading.Event, str, threading.Event]] = {}
        self._guard = threading.Lock()

    def probe(self, request: BackendProbeRequest) -> BackendProbeResult:
        return BackendProbeResult("coroutine", True, "available", "同进程 coroutine 后端可用。")

    def start(self, member: TeamMemberSnapshot) -> BackendStartResult:
        with self._guard:
            existing = self._runs.get(member.member_id)
            if existing is not None and not existing[0].done():
                return BackendStartResult(False, "coroutine", member.process, "成员实例已在运行。")
            cancel = threading.Event()
            wake = threading.Event()
            launch = threading.Event()
            token = secrets.token_urlsafe(24)
            future = self._executor.submit(self._run, member, cancel, wake, launch)
            self._runs[member.member_id] = (future, cancel, wake, token, launch)
            if not self.defer_start:
                launch.set()
        process = MemberProcessIdentity("coroutine", runtime_token=token)
        return BackendStartResult(True, "coroutine", process, "成员 coroutine 已启动。")

    def _run(
        self,
        member: TeamMemberSnapshot,
        cancel: threading.Event,
        wake: threading.Event,
        launch: threading.Event,
    ) -> object:
        launch.wait()
        result = self.runner(member, cancel, wake)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def release(self, member: TeamMemberSnapshot) -> None:
        with self._guard:
            run = self._runs.get(member.member_id)
            if run is not None:
                run[4].set()

    def wake(self, member: TeamMemberSnapshot, message_id: str) -> BackendWakeResult:
        with self._guard:
            run = self._runs.get(member.member_id)
            if run is None or run[0].done():
                return BackendWakeResult(False, "成员 coroutine 当前未运行；消息将在下次恢复时处理。")
            run[2].set()
        return BackendWakeResult(True)

    def stop(self, member: TeamMemberSnapshot, timeout_seconds: float) -> MemberStopResult:
        with self._guard:
            run = self._runs.get(member.member_id)
        if run is None:
            return MemberStopResult(True, "成员 coroutine 已停止。")
        run[1].set()
        run[2].set()
        run[4].set()
        try:
            run[0].result(timeout=timeout_seconds)
        except TimeoutError:
            return MemberStopResult(False, "等待成员 coroutine 停止超时。")
        except Exception:
            pass
        return MemberStopResult(True, "成员 coroutine 已停止。")

    def inspect(self, member: TeamMemberSnapshot) -> BackendStatus:
        with self._guard:
            run = self._runs.get(member.member_id)
        return BackendStatus(run is not None and not run[0].done())

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
