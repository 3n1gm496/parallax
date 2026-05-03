from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from parallax.db.models import OrderbookSnapshotRecord
from parallax.execution.schemas import OrderbookSnapshot, OrderbookSide, OrderbookLevel


class OrderbookSnapshotStore:
    """Persist and retrieve OrderbookSnapshot objects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, snap: OrderbookSnapshot) -> OrderbookSnapshotRecord:
        record = OrderbookSnapshotRecord(
            id=uuid.UUID(snap.id) if isinstance(snap.id, str) else snap.id,
            platform=snap.platform,
            raw_market_id=snap.market_id,
            token_id=snap.token_id,
            outcome=snap.outcome,
            captured_at=snap.captured_at,
            bid_levels=[lvl.model_dump() for lvl in snap.bids.levels],
            ask_levels=[lvl.model_dump() for lvl in snap.asks.levels],
            mid_price=snap.mid_price,
            spread_bps=snap.spread_bps,
            total_bid_depth=snap.bids.total_depth,
            total_ask_depth=snap.asks.total_depth,
        )
        self._session.add(record)
        return record

    async def get_latest(
        self,
        platform: str,
        market_id: str,
        outcome: str,
    ) -> OrderbookSnapshot | None:
        result = await self._session.execute(
            select(OrderbookSnapshotRecord)
            .where(
                OrderbookSnapshotRecord.platform == platform,
                OrderbookSnapshotRecord.raw_market_id == market_id,
                OrderbookSnapshotRecord.outcome == outcome,
            )
            .order_by(OrderbookSnapshotRecord.captured_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._record_to_snapshot(record)

    @staticmethod
    def _record_to_snapshot(record: OrderbookSnapshotRecord) -> OrderbookSnapshot:
        bids = OrderbookSide(
            levels=[OrderbookLevel(**lvl) for lvl in (record.bid_levels or [])]
        )
        asks = OrderbookSide(
            levels=[OrderbookLevel(**lvl) for lvl in (record.ask_levels or [])]
        )
        return OrderbookSnapshot(
            id=str(record.id),
            platform=record.platform,  # type: ignore[arg-type]
            market_id=record.raw_market_id,
            token_id=record.token_id,
            outcome=record.outcome,
            captured_at=record.captured_at,
            bids=bids,
            asks=asks,
            mid_price=record.mid_price,
            spread_bps=record.spread_bps,
        )
