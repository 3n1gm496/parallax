from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from parallax.config import Settings
from parallax.execution.fetcher import OrderbookFetcher
from parallax.execution.schemas import OrderbookSnapshot


def _fresh_snap(platform: str = "polymarket") -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id="snap-fetcher",
        platform=platform,  # type: ignore[arg-type]
        market_id="0xabc",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
    )


def _settings(enabled: bool = True) -> Settings:
    return Settings(orderbook_enabled=enabled)


@pytest.mark.anyio
async def test_fetch_disabled_returns_none():
    fetcher = OrderbookFetcher(_settings(enabled=False))
    result = await fetcher.fetch("polymarket", "0xabc", "YES", "tok-1")
    assert result is None


@pytest.mark.anyio
async def test_fetch_polymarket_no_token_returns_none():
    fetcher = OrderbookFetcher(_settings(enabled=True))
    result = await fetcher.fetch("polymarket", "0xabc", "YES", token_id=None)
    assert result is None


@pytest.mark.anyio
async def test_fetch_polymarket_delegates_to_clob_adapter():
    snap = _fresh_snap("polymarket")
    poly_mock = AsyncMock()
    poly_mock.fetch_snapshot = AsyncMock(return_value=snap)

    fetcher = OrderbookFetcher(_settings(enabled=True), polymarket_adapter=poly_mock)
    result = await fetcher.fetch("polymarket", "0xabc", "YES", "tok-1")

    assert result is snap
    poly_mock.fetch_snapshot.assert_called_once_with("0xabc", "YES", "tok-1")


@pytest.mark.anyio
async def test_fetch_kalshi_delegates_to_quote_adapter():
    snap = _fresh_snap("kalshi")
    kalshi_mock = AsyncMock()
    kalshi_mock.fetch_snapshot = AsyncMock(return_value=snap)

    fetcher = OrderbookFetcher(_settings(enabled=True), kalshi_adapter=kalshi_mock)
    result = await fetcher.fetch("kalshi", "KXTEST-24", "YES")

    assert result is snap
    kalshi_mock.fetch_snapshot.assert_called_once_with("KXTEST-24", "YES")


@pytest.mark.anyio
async def test_fetch_unknown_platform_returns_none():
    fetcher = OrderbookFetcher(_settings(enabled=True))
    result = await fetcher.fetch("unknown_venue", "mkid", "YES")
    assert result is None


@pytest.mark.anyio
async def test_fetcher_passes_kalshi_api_key_to_adapter():
    """OrderbookFetcher constructs KalshiQuoteAdapter with the api_key from settings."""
    snap = _fresh_snap("kalshi")
    kalshi_mock = AsyncMock()
    kalshi_mock.fetch_snapshot = AsyncMock(return_value=snap)

    settings_with_key = Settings(orderbook_enabled=True, kalshi_api_key="live-key-xyz")

    with patch(
        "parallax.execution.fetcher.KalshiQuoteAdapter", return_value=kalshi_mock
    ) as MockKalshi:
        fetcher = OrderbookFetcher(settings_with_key)
        await fetcher.fetch("kalshi", "KXTEST-24", "YES")

    init_kwargs = MockKalshi.call_args[1]
    assert init_kwargs.get("api_key") == "live-key-xyz"
