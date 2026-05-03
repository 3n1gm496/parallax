from __future__ import annotations

from sqlalchemy.orm import Session

from parallax.db.models import MarketEventLink, RawMarket
from parallax.event_frames.repository import EventFrameRepository


class EventFrameBuilder:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = EventFrameRepository(session)

    def build_for_markets(self, markets: list[RawMarket]) -> dict[str, str]:
        partition_candidates = self._partition_candidate_market_ids(markets)
        frame_ids: dict[str, str] = {}
        for market in markets:
            frame = self._frame_for_market(market)
            membership_type = "same_event_family"
            if market.id in partition_candidates:
                membership_type = "same_exhaustive_partition_candidate"
            self._repo.upsert_membership(
                raw_market_id=market.id,
                frame_id=frame.id,
                membership_type=membership_type,
                confidence=1.0,
                evidence={
                    "frame_key": frame.frame_key,
                    "frame_type": frame.frame_type,
                    "partition_candidate": market.id in partition_candidates,
                },
            )
            frame_ids[market.id] = str(frame.id)
        return frame_ids

    def _frame_for_market(self, market: RawMarket):
        link = (
            self._session.query(MarketEventLink)
            .filter(MarketEventLink.raw_market_id == market.id)
            .order_by(MarketEventLink.linked_at.desc())
            .first()
        )
        if link is not None:
            return self._repo.get_or_create_frame(
                frame_key=f"event:{link.canonical_event_id}",
                frame_type="canonical_event",
                title=market.title,
                domain=market.category or market.platform,
                canonical_event_id=link.canonical_event_id,
            )
        if market.group_id:
            return self._repo.get_or_create_frame(
                frame_key=f"group:{market.platform}:{market.group_id}",
                frame_type="platform_group",
                title=market.title,
                domain=market.category or market.platform,
            )
        return self._repo.get_or_create_frame(
            frame_key=f"market:{market.id}",
            frame_type="singleton",
            title=market.title,
            domain=market.category or market.platform,
        )

    @staticmethod
    def _partition_candidate_market_ids(markets: list[RawMarket]) -> set[str]:
        grouped: dict[tuple[str, str | None], list[RawMarket]] = {}
        for market in markets:
            grouped.setdefault((market.platform, market.group_id), []).append(market)
        candidates: set[str] = set()
        for (_, group_id), members in grouped.items():
            if not group_id or len(members) < 2:
                continue
            if all(len(member.outcomes or []) == 2 for member in members):
                candidates.update(member.id for member in members)
        return candidates
