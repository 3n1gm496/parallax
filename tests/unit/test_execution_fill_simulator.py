from __future__ import annotations

import pytest
from datetime import datetime, timezone

from parallax.execution.fill_simulator import DepthAwareFillSimulator, _fill_probability
from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot


def _snap(asks=None, bids=None) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id="snap-fill",
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=bids or OrderbookSide(),
        asks=asks or OrderbookSide(),
    )


def test_full_depth_high_fill_probability():
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.51, size=200.0)])
    sim = DepthAwareFillSimulator()
    result = sim.simulate(_snap(asks=asks), "buy", 100.0)

    assert result.fill_probability >= 0.9
    assert result.partial_fill_risk == pytest.approx(0.0)
    assert result.expected_fill_size == pytest.approx(100.0)


def test_partial_depth_above_threshold():
    # 70 available, need 100 → fill_ratio 0.7 → partial fill risk in (0,1)
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.51, size=70.0)])
    sim = DepthAwareFillSimulator(inversion_threshold=0.4)
    result = sim.simulate(_snap(asks=asks), "buy", 100.0)

    assert 0 < result.partial_fill_risk < 1
    assert result.fill_probability < 0.9


def test_depth_below_inversion_threshold_zero_risk():
    # 20 available, need 100 → fill_ratio 0.2 → below threshold → risk 0
    asks = OrderbookSide(levels=[OrderbookLevel(price=0.51, size=20.0)])
    sim = DepthAwareFillSimulator(inversion_threshold=0.4)
    result = sim.simulate(_snap(asks=asks), "buy", 100.0)

    assert result.partial_fill_risk == pytest.approx(0.0)


def test_empty_book_zero_fill():
    sim = DepthAwareFillSimulator()
    result = sim.simulate(_snap(), "buy", 100.0)

    assert result.expected_fill_size == pytest.approx(0.0)
    assert result.fill_probability == pytest.approx(0.0)
    assert result.expected_price is None


def test_fill_probability_thresholds():
    assert _fill_probability(1.0) == pytest.approx(0.95)
    assert _fill_probability(0.95) == pytest.approx(0.85)
    assert _fill_probability(0.8) == pytest.approx(0.70)
    assert _fill_probability(0.6) == pytest.approx(0.55)
    assert _fill_probability(0.3) == pytest.approx(0.15)
