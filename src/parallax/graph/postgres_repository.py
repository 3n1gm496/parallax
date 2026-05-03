from __future__ import annotations
import uuid
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from parallax.config import settings
from parallax.db.models import (
    CounterexampleRecord as CounterexampleRecordModel,
    LogicalRelation,
    LogicalRelationSet,
    MarketRelation,
    RelationReview,
)
from parallax.graph.repository import GraphRepository
from parallax.shared.schemas import CounterexampleRecord, RelationType


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
        proof_status, tradeable_relation = self._normalize_relation_flags(relation_type, evidence)
        logical_relation = LogicalRelation(
            id=uuid.uuid4(),
            from_market_id=from_market_id,
            to_market_id=to_market_id,
            frame_id=evidence.get("frame_id"),
            relation_type=relation_type.value,
            proof_status=proof_status,
            tradeable_relation=tradeable_relation,
            confidence=confidence,
            evidence={**evidence, "proof_status": proof_status, "tradeable_relation": tradeable_relation},
            created_by=created_by,
        )
        self._session.add(logical_relation)
        if settings.persist_market_relations_compat:
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
        return str(logical_relation.id)

    @staticmethod
    def _normalize_relation_flags(relation_type: RelationType, evidence: dict) -> tuple[str, bool]:
        proof_status = str(evidence.get("proof_status", "verified"))
        if "tradeable_relation" in evidence:
            return proof_status, bool(evidence["tradeable_relation"])
        if relation_type in {RelationType.MUTUALLY_EXCLUSIVE, RelationType.EQUIVALENT, RelationType.DUPLICATE}:
            return proof_status, True
        return proof_status, False

    def add_review(
        self,
        *,
        from_market_id: str,
        to_market_id: str,
        proposed_relation_type: RelationType,
        reviewed_relation_type: RelationType | None,
        proof_status: str,
        tradeable_relation: bool,
        review_payload: dict,
        reviewed_by: str,
    ) -> str:
        row = RelationReview(
            id=uuid.uuid4(),
            from_market_id=from_market_id,
            to_market_id=to_market_id,
            proposed_relation_type=proposed_relation_type.value,
            reviewed_relation_type=reviewed_relation_type.value if reviewed_relation_type is not None else None,
            proof_status=proof_status,
            tradeable_relation=tradeable_relation,
            review_payload=review_payload,
            reviewed_by=reviewed_by,
        )
        self._session.add(row)
        self._session.flush()
        return str(row.id)

    def add_relation_set(
        self,
        *,
        set_key: str,
        member_market_ids: list[str],
        relation_type: RelationType,
        confidence: float,
        evidence: dict,
        created_by: str,
    ) -> str:
        proof_status, tradeable_relation = self._normalize_relation_flags(relation_type, evidence)
        row = LogicalRelationSet(
            id=uuid.uuid4(),
            set_key=set_key,
            frame_id=evidence.get("frame_id"),
            member_market_ids=member_market_ids,
            relation_type=relation_type.value,
            proof_status=proof_status,
            tradeable_relation=tradeable_relation,
            confidence=confidence,
            evidence={**evidence, "proof_status": proof_status, "tradeable_relation": tradeable_relation},
            created_by=created_by,
        )
        self._session.add(row)
        self._session.flush()
        return str(row.id)

    def add_counterexample_record(self, record: CounterexampleRecord) -> str:
        row = CounterexampleRecordModel(
            id=uuid.uuid4(),
            relation_id=uuid.UUID(record.relation_id) if record.relation_id else None,
            review_id=uuid.UUID(record.review_id) if record.review_id else None,
            set_key=record.set_key,
            relation_type=record.relation_type.value,
            scenario_description=record.scenario_description,
            resolution_a=record.resolution_a,
            resolution_b=record.resolution_b,
            why_different=record.why_different,
            source=record.source,
            status=record.status,
            metadata_json=record.metadata,
            created_by=record.created_by,
        )
        self._session.add(row)
        self._session.flush()
        return str(row.id)

    def get_relations(
        self,
        market_id: str,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        q = self._session.query(LogicalRelation).filter(
            or_(
                LogicalRelation.from_market_id == market_id,
                LogicalRelation.to_market_id == market_id,
            )
        )
        if relation_type is not None:
            q = q.filter(LogicalRelation.relation_type == relation_type.value)
        return [self._to_dict(r) for r in q.all()]

    def get_relation_set(self, set_key: str) -> dict | None:
        row = self._session.query(LogicalRelationSet).filter(LogicalRelationSet.set_key == set_key).first()
        return self._to_set_dict(row) if row is not None else None

    def list_relation_sets(
        self,
        *,
        limit: int = 100,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        q = self._session.query(LogicalRelationSet).order_by(LogicalRelationSet.created_at.desc())
        if relation_type is not None:
            q = q.filter(LogicalRelationSet.relation_type == relation_type.value)
        return [self._to_set_dict(row) for row in q.limit(limit).all()]

    def relation_exists(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
    ) -> bool:
        return (
            self._session.query(LogicalRelation)
            .filter(
                or_(
                    and_(
                        LogicalRelation.from_market_id == from_market_id,
                        LogicalRelation.to_market_id == to_market_id,
                    ),
                    and_(
                        LogicalRelation.from_market_id == to_market_id,
                        LogicalRelation.to_market_id == from_market_id,
                    ),
                ),
                LogicalRelation.relation_type == relation_type.value,
            )
            .first()
        ) is not None

    def delete_relation(self, relation_id: str) -> bool:
        logical = self._session.get(LogicalRelation, uuid.UUID(relation_id))
        if logical is None:
            return False
        self._session.delete(logical)
        legacy = (
            self._session.query(MarketRelation)
            .filter(
                MarketRelation.from_market_id == logical.from_market_id,
                MarketRelation.to_market_id == logical.to_market_id,
                MarketRelation.relation_type == logical.relation_type,
            )
            .first()
        )
        if legacy is not None:
            self._session.delete(legacy)
        self._session.flush()
        return True

    @staticmethod
    def _to_dict(r: LogicalRelation) -> dict:
        return {
            "id": str(r.id),
            "from_market_id": r.from_market_id,
            "to_market_id": r.to_market_id,
            "relation_type": r.relation_type,
            "confidence": r.confidence,
            "evidence": r.evidence,
            "created_by": r.created_by,
            "proof_status": r.proof_status,
            "tradeable_relation": r.tradeable_relation,
            "frame_id": str(r.frame_id) if r.frame_id is not None else None,
        }

    @staticmethod
    def _to_set_dict(r: LogicalRelationSet) -> dict:
        return {
            "id": str(r.id),
            "set_key": r.set_key,
            "member_market_ids": list(r.member_market_ids or []),
            "relation_type": r.relation_type,
            "confidence": r.confidence,
            "evidence": r.evidence,
            "created_by": r.created_by,
            "proof_status": r.proof_status,
            "tradeable_relation": r.tradeable_relation,
            "frame_id": str(r.frame_id) if r.frame_id is not None else None,
        }
