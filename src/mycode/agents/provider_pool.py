from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace

import httpx

from mycode.providers.base import LLMProvider
from mycode.providers.factory import create_provider
from mycode.types import AppConfig, UserFacingError


ProviderBuilder = Callable[..., LLMProvider]


class ProviderPool:
    def __init__(
        self,
        base_config: AppConfig,
        *,
        provider_builder: ProviderBuilder = create_provider,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_config = base_config
        self._provider_builder = provider_builder
        self._client = client or httpx.Client(timeout=None)
        self._owns_client = client is None
        self._providers: dict[str, LLMProvider] = {}
        self._closed = False
        self._lock = threading.RLock()

    def get(self, model_id: str) -> LLMProvider:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("model_id 必须是非空字符串。")
        with self._lock:
            if self._closed:
                raise UserFacingError("ProviderPool 已关闭。")
            provider = self._providers.get(model_id)
            if provider is not None:
                return provider
            config = replace(self.base_config, model=model_id)
            provider = self._provider_builder(config, client=self._client)
            self._providers[model_id] = provider
            return provider

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._providers.clear()
            if self._owns_client:
                self._client.close()
