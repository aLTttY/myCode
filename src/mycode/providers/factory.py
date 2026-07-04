from __future__ import annotations

from mycode.types import AppConfig, ConfigError

from .base import LLMProvider


def create_provider(config: AppConfig) -> LLMProvider:
    if config.protocol == "openai":
        from .openai import OpenAIProvider

        return OpenAIProvider(config)
    if config.protocol == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(config)
    if config.protocol == "deepseek":
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider(config)
    raise ConfigError(f"不支持的 protocol：{config.protocol}")
