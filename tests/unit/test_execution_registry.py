from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from parallax.execution.registry import VenueTokenRegistry
from parallax.db.models import VenueToken


def _make_session(scalar_result=None):
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_result
    session.execute.return_value = result
    return session


@pytest.mark.anyio
async def test_get_token_id_returns_value():
    session = _make_session(scalar_result="tok-abc")
    registry = VenueTokenRegistry(session)
    tid = await registry.get_token_id("polymarket", "0xabc", "YES")
    assert tid == "tok-abc"


@pytest.mark.anyio
async def test_get_token_id_returns_none_when_missing():
    session = _make_session(scalar_result=None)
    registry = VenueTokenRegistry(session)
    tid = await registry.get_token_id("polymarket", "0xabc", "YES")
    assert tid is None


@pytest.mark.anyio
async def test_upsert_creates_new_row_when_missing():
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    registry = VenueTokenRegistry(session)
    row = await registry.upsert("polymarket", "0xabc", "YES", "tok-new")

    assert row.platform == "polymarket"
    assert row.raw_market_id == "0xabc"
    assert row.outcome == "YES"
    assert row.token_id == "tok-new"
    session.add.assert_called_once_with(row)


@pytest.mark.anyio
async def test_upsert_updates_existing_row():
    existing = VenueToken(
        id=uuid.uuid4(),
        platform="polymarket",
        raw_market_id="0xabc",
        outcome="YES",
        token_id="tok-old",
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing
    session.execute.return_value = result

    registry = VenueTokenRegistry(session)
    row = await registry.upsert("polymarket", "0xabc", "YES", "tok-new")

    assert row.token_id == "tok-new"
    session.add.assert_not_called()
