from __future__ import annotations

import json
import os
import queue
import re
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .models import (
    AgentAction,
    CommandAction,
    HookAction,
    HookActionOutcome,
    HookEvent,
    HTTPAction,
    PromptAction,
)


_MAX_OUTPUT_CHARS = 16_000
_MAX_REASON_CHARS = 2_000
_HTTP_TIMEOUT_SECONDS = 10.0
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:token|secret|password|api_?key)[A-Za-z0-9_]*)"
    r"\s*([:=])\s*([^\s,;]+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


@dataclass(frozen=True)
class _AsyncJob:
    action: CommandAction | HTTPAction
    event: HookEvent
    callback: Callable[[HookActionOutcome], None] | None
    workspace_root: Path
    process_environment: Mapping[str, str] | None


class HookActionExecutor:
    def __init__(
        self,
        workspace_root: Path,
        *,
        worker_count: int = 2,
        queue_size: int = 64,
        http_client_factory: Callable[..., httpx.Client] | None = None,
    ) -> None:
        if worker_count < 1 or queue_size < 1:
            raise ValueError("Hook worker_count 和 queue_size 必须为正数。")
        self.workspace_root = workspace_root.resolve()
        self._worker_count = worker_count
        self._http_client_factory = http_client_factory or httpx.Client
        self._jobs: queue.Queue[_AsyncJob] = queue.Queue(maxsize=queue_size)
        self._closing = threading.Event()
        self._state_lock = threading.Lock()
        self._active_processes: set[subprocess.Popen[bytes]] = set()
        self._active_clients: set[httpx.Client] = set()
        self._threads: tuple[threading.Thread, ...] = ()

    def execute(
        self,
        action: HookAction,
        event: HookEvent,
        callback: Callable[[HookActionOutcome], None] | None = None,
        *,
        workspace_root: Path | None = None,
        process_environment: Mapping[str, str] | None = None,
    ) -> HookActionOutcome:
        if self._closing.is_set():
            return HookActionOutcome("cancelled", "Hook 动作执行器已关闭。", "executor_closed")
        if isinstance(action, PromptAction):
            return HookActionOutcome(
                "failed",
                "prompt 动作必须由 Hook Runtime 排队。",
                "prompt_runtime_required",
            )
        if isinstance(action, AgentAction):
            return HookActionOutcome(
                "placeholder",
                "agent 动作尚未实现，本次未启动子 Agent。",
                "agent_not_implemented",
            )
        if action.asynchronous:
            if event.name == "tool_before":
                return HookActionOutcome(
                    "failed",
                    "tool_before 动作不允许异步。",
                    "async_interceptor_forbidden",
                )
            self._ensure_workers()
            if self._closing.is_set():
                return HookActionOutcome(
                    "cancelled",
                    "Hook 动作执行器已关闭。",
                    "executor_closed",
                )
            try:
                self._jobs.put_nowait(
                    _AsyncJob(
                        action,
                        event,
                        callback,
                        (workspace_root or self.workspace_root).resolve(),
                        process_environment,
                    )
                )
            except queue.Full:
                return HookActionOutcome(
                    "failed",
                    "Hook 异步队列已满。",
                    "async_queue_full",
                )
            return HookActionOutcome("submitted", code="async_submitted")
        if workspace_root is None and process_environment is None:
            return self._execute_sync(action, event)
        return self._execute_sync(
            action,
            event,
            workspace_root=workspace_root,
            process_environment=process_environment,
        )

    def _ensure_workers(self) -> None:
        with self._state_lock:
            if self._threads or self._closing.is_set():
                return
            self._threads = tuple(
                threading.Thread(
                    target=self._worker,
                    name=f"mycode-hook-{index + 1}",
                    daemon=True,
                )
                for index in range(self._worker_count)
            )
            threads = self._threads
        for thread in threads:
            thread.start()

    def close(self) -> None:
        if self._closing.is_set():
            return
        self._closing.set()
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            self._notify(
                job.callback,
                HookActionOutcome("cancelled", "Hook 执行器关闭，异步动作未运行。", "shutdown"),
            )
            self._jobs.task_done()
        with self._state_lock:
            processes = tuple(self._active_processes)
            clients = tuple(self._active_clients)
        for process in processes:
            _terminate_process(process)
        for client in clients:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - 清理边界不得影响主流程。
                pass

    def _worker(self) -> None:
        while not self._closing.is_set():
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self._closing.is_set():
                    outcome = HookActionOutcome(
                        "cancelled",
                        "Hook 执行器关闭，异步动作未运行。",
                        "shutdown",
                    )
                else:
                    if (
                        job.workspace_root == self.workspace_root
                        and job.process_environment is None
                    ):
                        outcome = self._execute_sync(job.action, job.event)
                    else:
                        outcome = self._execute_sync(
                            job.action,
                            job.event,
                            workspace_root=job.workspace_root,
                            process_environment=job.process_environment,
                        )
                self._notify(job.callback, outcome)
            finally:
                self._jobs.task_done()

    @staticmethod
    def _notify(
        callback: Callable[[HookActionOutcome], None] | None,
        outcome: HookActionOutcome,
    ) -> None:
        if callback is None:
            return
        try:
            callback(outcome)
        except Exception:  # noqa: BLE001 - 诊断回调不得杀死后台 worker。
            pass

    def _execute_sync(
        self,
        action: CommandAction | HTTPAction,
        event: HookEvent,
        *,
        workspace_root: Path | None = None,
        process_environment: Mapping[str, str] | None = None,
    ) -> HookActionOutcome:
        if self._closing.is_set():
            return HookActionOutcome("cancelled", "Hook 动作执行器已关闭。", "executor_closed")
        if isinstance(action, CommandAction):
            return self._execute_command(
                action,
                event,
                workspace_root=workspace_root,
                process_environment=process_environment,
            )
        return self._execute_http(action, event)

    def _execute_command(
        self,
        action: CommandAction,
        event: HookEvent,
        *,
        workspace_root: Path | None = None,
        process_environment: Mapping[str, str] | None = None,
    ) -> HookActionOutcome:
        payload = _event_json(event)
        environment = dict(os.environ)
        if process_environment:
            environment.update(process_environment)
        try:
            process = subprocess.Popen(
                action.command,
                shell=True,
                cwd=workspace_root or self.workspace_root,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except (OSError, ValueError):
            return HookActionOutcome("failed", "Hook command 启动失败。", "command_start_failed")

        with self._state_lock:
            self._active_processes.add(process)
        if self._closing.is_set():
            _terminate_process(process)
        stdout = bytearray()
        stderr = bytearray()
        readers = (
            threading.Thread(target=_drain_pipe, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=_drain_pipe, args=(process.stderr, stderr), daemon=True),
        )
        for reader in readers:
            reader.start()
        try:
            if process.stdin is not None:
                try:
                    process.stdin.write(payload)
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            try:
                return_code = process.wait(timeout=action.timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process(process)
                process.wait()
                return HookActionOutcome("failed", "Hook command 执行超时。", "command_timeout")
            finally:
                for reader in readers:
                    reader.join(timeout=1.0)

            if self._closing.is_set():
                return HookActionOutcome("cancelled", "Hook command 已取消。", "shutdown")
            if event.name == "tool_before" and return_code == 2:
                reason = _bounded_text(stderr) or "Hook 安全策略拒绝了该工具调用。"
                return HookActionOutcome("denied", reason, "command_denied")
            if return_code == 0:
                return HookActionOutcome("success", code="command_succeeded")
            return HookActionOutcome(
                "failed",
                f"Hook command 退出码为 {return_code}。",
                "command_failed",
            )
        except Exception:  # noqa: BLE001 - 外部进程边界必须失败隔离。
            _terminate_process(process)
            return HookActionOutcome("failed", "Hook command 执行失败。", "command_error")
        finally:
            with self._state_lock:
                self._active_processes.discard(process)

    def _execute_http(self, action: HTTPAction, event: HookEvent) -> HookActionOutcome:
        headers = dict(action.headers)
        headers["Content-Type"] = "application/json"
        try:
            client = self._http_client_factory(timeout=_HTTP_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - 工厂属于外部边界。
            return HookActionOutcome("failed", "Hook HTTP 客户端创建失败。", "http_client_error")
        with self._state_lock:
            self._active_clients.add(client)
        if self._closing.is_set():
            try:
                client.close()
            except Exception:  # noqa: BLE001 - 清理边界不得影响主流程。
                pass
            with self._state_lock:
                self._active_clients.discard(client)
            return HookActionOutcome("cancelled", "Hook HTTP 已取消。", "shutdown")
        try:
            with client.stream(
                action.method,
                action.url,
                headers=headers,
                content=_event_json(event),
            ) as response:
                body = _read_response(response)
                status_code = response.status_code
            if not 200 <= status_code < 300:
                return HookActionOutcome(
                    "failed",
                    f"Hook HTTP 响应状态为 {status_code}。",
                    "http_status",
                )
            if event.name != "tool_before":
                return HookActionOutcome("success", code="http_succeeded")
            return _http_decision(body)
        except httpx.TimeoutException:
            return HookActionOutcome("failed", "Hook HTTP 请求超时。", "http_timeout")
        except httpx.HTTPError:
            return HookActionOutcome("failed", "Hook HTTP 请求失败。", "http_error")
        except Exception:  # noqa: BLE001 - 自定义 transport 也必须失败隔离。
            return HookActionOutcome("failed", "Hook HTTP 请求失败。", "http_error")
        finally:
            with self._state_lock:
                self._active_clients.discard(client)
            try:
                client.close()
            except Exception:  # noqa: BLE001 - 清理失败不得影响 Agent。
                pass


def _event_json(event: HookEvent) -> bytes:
    return json.dumps(
        event.payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _drain_pipe(pipe: Any, target: bytearray) -> None:
    if pipe is None:
        return
    try:
        while True:
            chunk = pipe.read(8192)
            if not chunk:
                break
            remaining = _MAX_OUTPUT_CHARS - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
    except (OSError, ValueError):
        pass
    finally:
        try:
            pipe.close()
        except (OSError, ValueError):
            pass


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _bounded_text(value: bytes | bytearray) -> str:
    return _safe_text(bytes(value).decode("utf-8", errors="replace"))


def _safe_text(value: str) -> str:
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2<redacted>", value)
    redacted = _BEARER_SECRET.sub("Bearer <redacted>", redacted)
    return redacted.strip()[:_MAX_REASON_CHARS]


def _read_response(response: httpx.Response) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        remaining = _MAX_OUTPUT_CHARS - len(body)
        if remaining > 0:
            body.extend(chunk[:remaining])
    return bytes(body)


def _http_decision(body: bytes) -> HookActionOutcome:
    try:
        value = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HookActionOutcome("failed", "Hook HTTP 返回了无效决策。", "http_invalid_decision")
    if not isinstance(value, dict):
        return HookActionOutcome("failed", "Hook HTTP 返回了无效决策。", "http_invalid_decision")
    if value == {"decision": "allow"}:
        return HookActionOutcome("success", code="http_allowed")
    if set(value) == {"decision", "reason"} and value.get("decision") == "deny":
        reason = value.get("reason")
        if isinstance(reason, str) and reason.strip():
            return HookActionOutcome("denied", _safe_text(reason), "http_denied")
    return HookActionOutcome("failed", "Hook HTTP 返回了无效决策。", "http_invalid_decision")
