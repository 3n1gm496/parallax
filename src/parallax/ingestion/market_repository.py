from __future__ import annotations
from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from parallax.db.models import MarketEventLink
from parallax.db.models import RawMarket
from parallax.shared.schemas import RawMarketData


class MarketRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, data: RawMarketData) -> tuple[RawMarket, bool]:
        """Insert or update a market. Returns (model, created)."""
        composite_id = f"{data.platform}:{data.market_id}"
        existing = self._session.get(RawMarket, composite_id)
        if existing is None:
            market = RawMarket(
                id=composite_id,
                platform=data.platform,
                market_id=data.market_id,
                title=data.title,
                description=data.description,
                resolution_criteria=data.resolution_criteria,
                outcomes=data.outcomes,
                outcome_prices=data.outcome_prices,
                category=data.category,
                group_id=data.group_id,
                deadline=data.deadline,
                is_closed=data.is_closed,
                resolution_source=data.resolution_source,
                raw_payload=data.raw_payload,
            )
            self._session.add(market)
            return market, True
        else:
            existing.title = data.title
            existing.description = data.description
            existing.resolution_criteria = data.resolution_criteria
            existing.outcomes = data.outcomes
            existing.outcome_prices = data.outcome_prices
            existing.category = data.category
            existing.group_id = data.group_id
            existing.deadline = data.deadline
            existing.is_closed = data.is_closed
            existing.resolution_source = data.resolution_source
            existing.raw_payload = data.raw_payload
            return existing, False

    def get(self, market_id: str) -> RawMarket | None:
        return self._session.get(RawMarket, market_id)

    def list_open(
        self, platform: str | None = None, limit: int = 1000, offset: int = 0
    ) -> list[RawMarket]:
        q = self._session.query(RawMarket).filter_by(is_closed=False)
        if platform:
            q = q.filter_by(platform=platform)
        return q.offset(offset).limit(limit).all()

    def list_by_group(self, group_id: str) -> list[RawMarket]:
        return (
            self._session.query(RawMarket)
            .filter_by(group_id=group_id, is_closed=False)
            .all()
        )

    def list_unlinked_open(self) -> list[RawMarket]:
        link_exists = select(MarketEventLink.raw_market_id).where(
            MarketEventLink.raw_market_id == RawMarket.id
        ).exists()
        return (
            self._session.query(RawMarket)
            .filter(RawMarket.is_closed.is_(False))
            .filter(~link_exists)
            .all()
        )
