from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from parallax.execution.schemas import (
    DepthAnalysis,
    OrderbookLevel,
    OrderbookSide,
    OrderbookSnapshot,
)


def test_orderbook_side_total_depth():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.45, size=100.0),
        OrderbookLevel(price=0.44, size=50.0),
    ])
    assert side.total_depth == 150.0


def test_orderbook_side_depth_at_or_better_bid():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.45, size=100.0),
        OrderbookLevel(price=0.44, size=50.0),
        OrderbookLevel(price=0.42, size=80.0),
    ])
    assert side.depth_at_or_better(0.44, "bid") == 150.0


def test_orderbook_side_depth_at_or_better_ask():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.46, size=100.0),
        OrderbookLevel(price=0.47, size=50.0),
        OrderbookLevel(price=0.50, size=80.0),
    ])
    # asks at 0.47 or better (≤ 0.47) for a buyer: 0.46 + 0.47 = 150
    assert side.depth_at_or_better(0.47, "ask") == 150.0


def test_orderbook_side_vwap_exact_fill():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.46, size=50.0),
        OrderbookLevel(price=0.47, size=100.0),
    ])
    vwap = side.vwap(60.0, side="ask")
    assert vwap is not None
    expected = (50 * 0.46 + 10 * 0.47) / 60
    assert abs(vwap - expected) < 1e-9


def test_orderbook_side_vwap_full_depth():
    side = OrderbookSide(levels=[OrderbookLevel(price=0.46, size=100.0)])
    vwap = side.vwap(100.0, side="ask")
    assert vwap == pytest.approx(0.46)


def test_orderbook_side_vwap_insufficient_depth_returns_none():
    side = OrderbookSide(levels=[OrderbookLevel(price=0.46, size=10.0)])
    assert side.vwap(100.0, side="ask") is None


def test_orderbook_side_vwap_empty_returns_none():
    side = OrderbookSide()
    assert side.vwap(100.0) is None


def test_orderbook_snapshot_is_stale():
    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    snap = OrderbookSnapshot(
        id="test-id",
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=old_ts,
    )
    assert snap.is_stale is True
    assert snap.staleness_seconds > 0


def test_orderbook_snapshot_is_fresh():
    snap = OrderbookSnapshot(
        id="test-id",
        platform="kalshi",
        market_id="KXSOME-24NOV-B0.5",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
    )
    assert snap.is_stale is False


def test_orderbook_snapshot_staleness_naive_ts():
    old_ts = datetime(2020, 1, 1)  # naive
    snap = OrderbookSnapshot(
        id="test-id",
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=old_ts,
    )
    assert snap.staleness_seconds > 0
    assert snap.is_stale is True


def test_depth_analysis_fields():
    da = DepthAnalysis(
        market_id="0xabc",
        outcome="YES",
        required_size=100.0,
        available_depth=200.0,
        is_supported=True,
        vwap_price=0.47,
        price_impact_bps=21.7,
        snapshot_id="snap-1",
    )
    assert da.is_supported is True
    assert da.vwap_price == 0.47
