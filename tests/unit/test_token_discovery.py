from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from parallax.shared.schemas import RawMarketData


def _make_raw(platform: str, ext_id: str, token_ids: dict) -> RawMarketData:
    return RawMarketData(
        platform=platform,
        market_id=ext_id,
        title="T",
        description="",
        resolution_criteria="",
        outcomes=list(token_ids.keys()) or ["YES", "NO"],
        outcome_prices=[0.5] * max(len(token_ids), 2),
        deadline=datetime(2026, 1, 1, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
        token_ids=token_ids,
    )


def _make_session(existing_id=None):
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_id
    session.execute.return_value = result
    return session


class TestTokenDiscoveryService:
    def test_upserts_tokens_for_polymarket(self):
        from parallax.execution.token_discovery import TokenDiscoveryService
        session = _make_session(existing_id=None)
        markets = [_make_raw("polymarket", "mkt-1", {"YES": "tok-yes", "NO": "tok-no"})]
        count = TokenDiscoveryService(session).process(markets)
        assert count == 2
        assert session.add.call_count == 2

    def test_skips_existing_tokens(self):
        from parallax.execution.token_discovery import TokenDiscoveryService
        session = _make_session(existing_id="existing-uuid")
        markets = [_make_raw("polymarket", "mkt-1", {"YES": "tok-yes"})]
        count = TokenDiscoveryService(session).process(markets)
        assert count == 0
        session.add.assert_not_called()

    def test_skips_non_polymarket(self):
        from parallax.execution.token_discovery import TokenDiscoveryService
        session = _make_session()
        markets = [_make_raw("kalshi", "mkt-k", {"YES": "tok-k"})]
        count = TokenDiscoveryService(session).process(markets)
        assert count == 0
        session.add.assert_not_called()

    def test_skips_empty_token_ids(self):
        from parallax.execution.token_discovery import TokenDiscoveryService
        session = _make_session()
        markets = [_make_raw("polymarket", "mkt-1", {})]
        count = TokenDiscoveryService(session).process(markets)
        assert count == 0
        session.add.assert_not_called()

    def test_multiple_markets(self):
        from parallax.execution.token_discovery import TokenDiscoveryService
        session = _make_session(existing_id=None)
        markets = [
            _make_raw("polymarket", "mkt-1", {"YES": "t1"}),
            _make_raw("polymarket", "mkt-2", {"YES": "t2", "NO": "t3"}),
            _make_raw("kalshi", "mkt-k", {"YES": "t4"}),
        ]
        count = TokenDiscoveryService(session).process(markets)
        assert count == 3
        assert session.add.call_count == 3
