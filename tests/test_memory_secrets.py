from mycode.memory.secrets import find_secret


def test_secret_scanner_blocks_credentials_and_allows_placeholders() -> None:
    assert find_secret("api_key=sk-abcdefghijklmnop") is not None
    assert find_secret("-----BEGIN PRIVATE KEY-----") == "private_key"
    assert find_secret("api_key=${API_KEY}") is None
    assert find_secret("token=<TOKEN>") is None
