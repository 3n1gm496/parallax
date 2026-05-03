from __future__ import annotations

import pytest
from datetime import datetime, timezone

from parallax.execution.estimator import DepthAwareExecutablePriceEstimator
from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot


def _snap(bids=None, asks=None, mid=0.50) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id="snap-est",
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=bids or OrderbookSide(),
        asks=asks or OrderbookSide(),
        mid_price=mid,
    )


def test_estimate_buy_full_depth():
    asks = OrderbookSide(levels=[
        OrderbookLevel(price=0.51, size=100.0),
        OrderbookLevel(price=0.52, size=50.0),
    ])
    snap = _snap(asks=asks, mid=0.50)
    est = DepthAwareExecutablePriceEstimator()
    result = est.estimate(snap, "buy", 80.0)

    assert result.is_supported is True
    assert result.vwap_price is not None
    assert result.vwap_price > 0.50
    assert result.available_depth == pytest.approx(150.0)
    assert result.price_impact_bps is not None


def test_estimate_sell_full_depth():
    bids = OrderbookSide(levels=[OrderbookLevel(price=0.49, size=200.0)])
    snap = _snap(bids=bids, mid=0.50)
    est = DepthAwareExecutablePriceEstimator()
    result = est.estimate(snap, "sell", 50.0)

    assert result.is_supported is True
    assert result.vwap_price == pytest.approx(0.49)


def test_estimate_insufficient_depth_not_supported():
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.51, size=10.0)])
    snap = _snap(asks=asks)
    est = DepthAwareExecutablePriceEstimator()
    result = est.estimate(snap, "buy", 100.0)

    assert result.is_supported is False
    assert result.vwap_price is None


def test_estimate_empty_book_not_supported():
    snap = _snap()
    est = DepthAwareExecutablePriceEstimator()
    result = est.estimate(snap, "buy", 50.0)

    assert result.is_supported is False
    assert result.available_depth == 0.0


def test_to_depth_analysis_fields():
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.51, size=200.0)])
    snap = _snap(asks=asks, mid=0.50)
    est = DepthAwareExecutablePriceEstimator()
    ep = est.estimate(snap, "buy", 50.0)
    da = ep.to_depth_analysis()

    assert da.market_id == "0xabc"
    assert da.is_supported is True
    assert da.snapshot_id == "snap-est"
