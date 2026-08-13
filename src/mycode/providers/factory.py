from __future__ import annotations

from mycode.types import AppConfig, ConfigError
import httpx

from .base import LLMProvider


def create_provider(
    config: AppConfig, *, client: httpx.Client | None = None
) -> LLMProvider:
    if config.protocol == "openai":
        from .openai import OpenAIProvider

        return OpenAIProvider(config, client=client)
    if config.protocol == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(config, client=client)
    if config.protocol == "deepseek":
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider(config, client=client)
    raise ConfigError(f"不支持的 protocol：{config.protocol}")
