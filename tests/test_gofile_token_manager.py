import asyncio

from dler_kun.engines.gofile.gofile_dl.downloader.go_file_api import (
    _retry_after_seconds,
)
from dler_kun.engines.gofile.gofile_dl.token.token_manager import TokenManager


def test_get_valid_token_skips_invalid_tokens(monkeypatch) -> None:
    monkeypatch.delenv("GF_TOKEN", raising=False)
    manager = TokenManager.__new__(TokenManager)
    manager.tokens = [
        {"token": "stale-token", "valid": False},
        {"token": "active-token", "valid": True},
    ]

    assert asyncio.run(manager.get_valid_token()) == "active-token"


def test_get_valid_token_returns_none_when_no_active_tokens(monkeypatch) -> None:
    monkeypatch.delenv("GF_TOKEN", raising=False)
    manager = TokenManager.__new__(TokenManager)
    manager.tokens = [{"token": "stale-token", "valid": False}]

    assert asyncio.run(manager.get_valid_token()) is None


def test_retry_after_is_bounded() -> None:
    assert _retry_after_seconds({"Retry-After": "5"}) == 5
    assert _retry_after_seconds({"Retry-After": "9999"}) == 120
    assert _retry_after_seconds({"Retry-After": "invalid"}) == 10
