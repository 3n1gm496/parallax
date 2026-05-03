from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from parallax.execution.snapshot_store import OrderbookSnapshotStore
from parallax.execution.schemas import OrderbookSnapshot, OrderbookSide, OrderbookLevel
from parallax.db.models import OrderbookSnapshotRecord


def _make_fresh_snapshot(snap_id: str = "00000000-0000-0000-0000-000000000001") -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id=snap_id,
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=0.45, size=100.0)]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=0.46, size=80.0)]),
        mid_price=0.455,
        spread_bps=21.9,
    )


@pytest.mark.anyio
async def test_save_adds_record_to_session():
    session = AsyncMock(spec=AsyncSession)
    store = OrderbookSnapshotStore(session)
    snap = _make_fresh_snapshot()

    record = await store.save(snap)

    assert str(record.id) == snap.id
    assert record.platform == "polymarket"
    assert record.raw_market_id == "0xabc"
    assert record.outcome == "YES"
    assert record.mid_price == pytest.approx(0.455)
    assert record.total_bid_depth == pytest.approx(100.0)
    assert record.total_ask_depth == pytest.approx(80.0)
    session.add.assert_called_once_with(record)


@pytest.mark.anyio
async def test_get_latest_returns_none_when_missing():
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    store = OrderbookSnapshotStore(session)
    snap = await store.get_latest("polymarket", "0xabc", "YES")
    assert snap is None


@pytest.mark.anyio
async def test_get_latest_round_trips_snapshot():
    snap_id = uuid.uuid4()
    snap_id_str = str(snap_id)
    now = datetime.now(timezone.utc)

    record = OrderbookSnapshotRecord(
        id=snap_id,
        platform="polymarket",
        raw_market_id="0xabc",
        token_id=None,
        outcome="YES",
        captured_at=now,
        bid_levels=[{"price": 0.45, "size": 100.0}],
        ask_levels=[{"price": 0.46, "size": 80.0}],
        mid_price=0.455,
        spread_bps=21.9,
        total_bid_depth=100.0,
        total_ask_depth=80.0,
        created_at=now,
    )
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = record
    session.execute.return_value = result

    store = OrderbookSnapshotStore(session)
    loaded = await store.get_latest("polymarket", "0xabc", "YES")

    assert loaded is not None
    assert loaded.id == snap_id_str
    assert loaded.mid_price == pytest.approx(0.455)
    assert len(loaded.bids.levels) == 1
    assert loaded.bids.levels[0].price == pytest.approx(0.45)
