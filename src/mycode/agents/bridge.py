from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import asdict

from mycode.providers.base import ChatRequest
from mycode.tools.registry import ToolRegistry
from mycode.types import UserFacingError

from .models import ForkRequestSnapshot


def request_fingerprint(request: ChatRequest) -> str:
    payload = asdict(request)
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def freeze_parent_request(
    session_id: str,
    mode: str,
    request: ChatRequest,
    registry: ToolRegistry,
) -> ForkRequestSnapshot:
    if mode not in {"default", "plan"}:
        raise ValueError("mode 必须是 default 或 plan。")
    frozen_request = copy.deepcopy(request)
    return ForkRequestSnapshot(
        session_id=session_id,
        mode=mode,
        request=frozen_request,
        registry=registry.copy(),
        request_fingerprint=request_fingerprint(frozen_request),
    )


class ParentRequestBridge:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: ForkRequestSnapshot | None = None

    def publish(self, snapshot: ForkRequestSnapshot) -> None:
        with self._lock:
            self._current = snapshot

    def current(self, session_id: str) -> ForkRequestSnapshot:
        with self._lock:
            snapshot = self._current
            if snapshot is None or snapshot.session_id != session_id:
                raise UserFacingError("当前没有可用于 Fork 的父请求快照。")
            return snapshot

    def clear(self, request_fingerprint_value: str | None = None) -> None:
        with self._lock:
            if self._current is None:
                return
            if (
                request_fingerprint_value is None
                or self._current.request_fingerprint == request_fingerprint_value
            ):
                self._current = None
