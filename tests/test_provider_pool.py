from concurrent.futures import ThreadPoolExecutor

import httpx

from mycode.agents.provider_pool import ProviderPool
from mycode.types import AppConfig


class FakeProvider:
    def __init__(self, config: AppConfig, client: httpx.Client) -> None:
        self.config = config
        self.client = client


def config() -> AppConfig:
    return AppConfig("openai", "parent", "https://example.com", "key")


def test_provider_pool_reuses_provider_and_shared_client() -> None:
    calls: list[FakeProvider] = []

    def build(app_config: AppConfig, *, client: httpx.Client) -> FakeProvider:
        provider = FakeProvider(app_config, client)
        calls.append(provider)
        return provider

    pool = ProviderPool(config(), provider_builder=build)
    with ThreadPoolExecutor(max_workers=8) as executor:
        same = list(executor.map(lambda _: pool.get("small"), range(16)))
    other = pool.get("large")

    assert len({id(item) for item in same}) == 1
    assert same[0].config.model == "small"
    assert other.config.model == "large"
    assert same[0].client is other.client
    assert len(calls) == 2
    pool.close()
    pool.close()


def test_provider_pool_rejects_get_after_close() -> None:
    pool = ProviderPool(config())
    pool.close()

    try:
        pool.get("small")
    except Exception as exc:
        assert "已关闭" in str(exc)
    else:
        raise AssertionError("closed pool accepted get")
