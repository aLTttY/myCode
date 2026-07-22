from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from .loader import SessionLoader
from .models import CleanupResult, SessionLoadResult, SessionWarning


class SessionCatalog:
    def __init__(self, workspace_root: Path, loader: SessionLoader | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        self.root = self.workspace_root / ".mycode" / "sessions"
        self.loader = loader or SessionLoader()

    def latest(self, now: datetime | None = None) -> SessionLoadResult | None:
        current = now or datetime.now().astimezone()
        candidates: list[SessionLoadResult] = []
        for path in self._paths():
            result = self.loader.load(path, current)
            if result.summary is None or not result.messages:
                continue
            if current - result.summary.last_active_at > timedelta(days=30):
                continue
            candidates.append(result)
        if not candidates:
            return None
        return max(candidates, key=self._candidate_key)

    def cleanup_expired(self, now: datetime | None = None) -> CleanupResult:
        current = now or datetime.now().astimezone()
        removed = 0
        warnings: list[SessionWarning] = []
        for path in self._paths():
            result = self.loader.load(path, current)
            if result.summary is not None:
                last = result.summary.last_active_at
                session_id = result.summary.session_id
            else:
                try:
                    last = datetime.fromtimestamp(path.stat().st_mtime, tz=current.tzinfo)
                except OSError:
                    continue
                session_id = path.stem
            if current - last <= timedelta(days=30):
                continue
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                warnings.append(SessionWarning("cleanup_failed", session_id, f"删除失败（{type(exc).__name__}）。"))
        return CleanupResult(removed=removed, warnings=tuple(warnings))

    def _paths(self) -> tuple[Path, ...]:
        if not self.root.is_dir() or self.root.is_symlink():
            return ()
        return tuple(path for path in sorted(self.root.glob("*.jsonl")) if path.is_file() and not path.is_symlink())

    @staticmethod
    def _candidate_key(result: SessionLoadResult) -> tuple[datetime, str]:
        if result.summary is None:
            raise ValueError("候选会话缺少摘要。")
        return result.summary.last_active_at, result.summary.session_id
