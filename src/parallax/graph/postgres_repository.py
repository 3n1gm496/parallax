from __future__ import annotations
import uuid
from sqlalchemy import or_
from sqlalchemy.orm import Session
from parallax.db.models import MarketRelation
from parallax.graph.repository import GraphRepository
from parallax.shared.schemas import RelationType


class PostgresGraphRepository(GraphRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_relation(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
        confidence: float,
        evidence: dict,
        created_by: str,
    ) -> str:
        relation = MarketRelation(
            id=uuid.uuid4(),
            from_market_id=from_market_id,
            to_market_id=to_market_id,
            relation_type=relation_type.value,
            confidence=confidence,
            evidence=evidence,
            created_by=created_by,
        )
        self._session.add(relation)
        self._session.flush()
        return str(relation.id)

    def get_relations(
        self,
        market_id: str,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        q = self._session.query(MarketRelation).filter(
            or_(
                MarketRelation.from_market_id == market_id,
                MarketRelation.to_market_id == market_id,
            )
        )
        if relation_type is not None:
            q = q.filter(MarketRelation.relation_type == relation_type.value)
        return [self._to_dict(r) for r in q.all()]

    def relation_exists(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
    ) -> bool:
        return (
            self._session.query(MarketRelation)
            .filter_by(
                from_market_id=from_market_id,
                to_market_id=to_market_id,
                relation_type=relation_type.value,
            )
            .first()
        ) is not None

    def delete_relation(self, relation_id: str) -> bool:
        relation = self._session.get(MarketRelation, uuid.UUID(relation_id))
        if relation is None:
            return False
        self._session.delete(relation)
        self._session.flush()
        return True

    @staticmethod
    def _to_dict(r: MarketRelation) -> dict:
        return {
            "id": str(r.id),
            "from_market_id": r.from_market_id,
            "to_market_id": r.to_market_id,
            "relation_type": r.relation_type,
            "confidence": r.confidence,
            "evidence": r.evidence,
            "created_by": r.created_by,
        }
