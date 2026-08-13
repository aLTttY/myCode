from __future__ import annotations

import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .manager import WorktreeManager
from .models import CleanupReport, WorktreeDiagnostic


class WorktreeJanitor:
    def __init__(
        self,
        main_workspace: Path,
        manager: WorktreeManager,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.main_workspace = main_workspace.resolve(strict=True)
        self.manager = manager
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._closing = threading.Event()
        self._scan_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="mycode-worktree-janitor",
            daemon=True,
        )
        self._thread.start()

    def scan_once(self) -> CleanupReport:
        if not self._scan_lock.acquire(blocking=False):
            return CleanupReport(
                0,
                1,
                0,
                (WorktreeDiagnostic("warning", "scan_already_running", None, "Worktree 清理扫描已在运行。"),),
            )
        cleaned = skipped = failed = 0
        diagnostics: list[WorktreeDiagnostic] = []
        try:
            cutoff = self.clock() - timedelta(seconds=self.manager.config.stale_after_seconds)
            try:
                candidates, candidate_diagnostics = self.manager.managed_candidate_scan(
                    self.main_workspace
                )
                diagnostics.extend(candidate_diagnostics)
            except Exception:
                return CleanupReport(
                    0,
                    0,
                    1,
                    (WorktreeDiagnostic("error", "candidate_scan_failed", None, "无法枚举 Worktree 清理候选。"),),
                )
            for identity in candidates:
                if self._closing.is_set():
                    skipped += 1
                    break
                if identity.lifecycle_state == "creating":
                    skipped += 1
                    diagnostics.append(
                        WorktreeDiagnostic("warning", "incomplete_identity", None, f"任务 {identity.task_id} 身份尚未完整，已跳过。")
                    )
                    continue
                if identity.last_active_at > cutoff:
                    skipped += 1
                    continue
                disposition = self.manager.delete(
                    identity,
                    lock_timeout_seconds=0.01,
                )
                if disposition.status == "cleaned":
                    cleaned += 1
                elif disposition.status in {"retained_changes", "retained_commits"}:
                    skipped += 1
                    diagnostics.append(
                        WorktreeDiagnostic("warning", disposition.status, None, f"任务 {identity.task_id} 未满足保护性清理条件。")
                    )
                elif "正在使用" in disposition.reason:
                    skipped += 1
                else:
                    failed += 1
                    diagnostics.append(
                        WorktreeDiagnostic("error", "cleanup_failed", None, f"任务 {identity.task_id} 清理失败。")
                    )
            return CleanupReport(cleaned, skipped, failed, tuple(diagnostics))
        finally:
            self._scan_lock.release()

    def close(self, timeout_seconds: float) -> None:
        self._closing.set()
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout_seconds))

    def _run(self) -> None:
        while not self._closing.is_set():
            try:
                self.scan_once()
            except Exception:
                pass
            if self._closing.wait(self.manager.config.cleanup_interval_seconds):
                return
