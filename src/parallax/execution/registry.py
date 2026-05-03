from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from parallax.db.models import VenueToken


class VenueTokenRegistry:
    """Map (platform, raw_market_id, outcome) → token_id and back."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_token_id(self, platform: str, market_id: str, outcome: str) -> str | None:
        result = await self._session.execute(
            select(VenueToken.token_id).where(
                VenueToken.platform == platform,
                VenueToken.raw_market_id == market_id,
                VenueToken.outcome == outcome,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, platform: str, market_id: str, outcome: str, token_id: str) -> VenueToken:
        existing = await self._session.execute(
            select(VenueToken).where(
                VenueToken.platform == platform,
                VenueToken.raw_market_id == market_id,
                VenueToken.outcome == outcome,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            row.token_id = token_id
            return row
        row = VenueToken(
            id=uuid.uuid4(),
            platform=platform,
            raw_market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        return row

    async def list_for_market(self, platform: str, market_id: str) -> list[VenueToken]:
        result = await self._session.execute(
            select(VenueToken).where(
                VenueToken.platform == platform,
                VenueToken.raw_market_id == market_id,
            )
        )
        return list(result.scalars().all())
