from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.db.models import RawMarket
from parallax.detection.stage1 import Stage1ConstraintDetector
from parallax.graph.repository import GraphRepository


class ProverService:
    """Orchestrate relation detection and persist results to the graph."""

    _CREATED_BY = "stage1_constraint"

    def __init__(self, session: Session, graph_repo: GraphRepository) -> None:
        self._session = session
        self._graph_repo = graph_repo
        self._detector = Stage1ConstraintDetector()

    def run(self, markets: list[RawMarket]) -> int:
        """Detect and persist new relations. Returns count of relations added."""
        specs = self._detector.detect(markets)
        added = 0
        for spec in specs:
            if not self._graph_repo.relation_exists(
                spec.from_market_id, spec.to_market_id, spec.relation_type
            ):
                self._graph_repo.add_relation(
                    from_market_id=spec.from_market_id,
                    to_market_id=spec.to_market_id,
                    relation_type=spec.relation_type,
                    confidence=spec.confidence,
                    evidence=spec.evidence,
                    created_by=self._CREATED_BY,
                )
                added += 1
        return added
