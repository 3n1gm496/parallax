from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from parallax.db.models import VenueToken
from parallax.shared.schemas import RawMarketData

log = logging.getLogger(__name__)


class TokenDiscoveryService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def process(self, markets: list[RawMarketData]) -> int:
        count = 0
        for market in markets:
            if market.platform != "polymarket":
                continue
            for outcome, token_id in market.token_ids.items():
                if not token_id:
                    continue
                existing = self._session.execute(
                    select(VenueToken.id).where(
                        VenueToken.platform == market.platform,
                        VenueToken.raw_market_id == market.market_id,
                        VenueToken.outcome == outcome,
                    )
                ).scalar_one_or_none()
                if existing is None:
                    self._session.add(VenueToken(
                        platform=market.platform,
                        raw_market_id=market.market_id,
                        token_id=token_id,
                        outcome=outcome,
                    ))
                    count += 1
                    log.debug(
                        "token_discovery: upserted %s/%s/%s",
                        market.platform,
                        market.market_id,
                        outcome,
                    )
        return count
