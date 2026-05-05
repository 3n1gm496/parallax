from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from parallax.db.models import EventIdentityCluster, IdentityClusterMember, RawMarket
from parallax.identity.alignment_engine import SemanticAlignmentEngine
from parallax.identity.normalizer import DeadlineNormalizer, EntityNormalizer, SourceNormalizer
from parallax.shared.schemas import IdentityType

_SCORER_VERSION = "identity-v3"
_MIN_CLUSTER_CONFIDENCE = 0.55


@dataclass
class ClusterDecision:
    cluster_id: uuid.UUID
    identity_type: IdentityType
    confidence: float
    provenance: dict = field(default_factory=dict)
    blocking_reason: str | None = None


class ClusterEngine:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._alignment_engine = SemanticAlignmentEngine()
        self._entity_n = EntityNormalizer()
        self._source_n = SourceNormalizer()
        self._deadline_n = DeadlineNormalizer()

    def score_pair(self, market_a, market_b) -> dict:
        return self._alignment_engine.align_pair(market_a, market_b)

    def classify_pair(self, market_a, market_b) -> IdentityType:
        res = self._alignment_engine.align_pair(market_a, market_b)
        return res["identity_type"]

    def find_or_create_singleton_cluster(self, canonical_event_id: uuid.UUID, raw_market_id: str) -> EventIdentityCluster:
        cluster_key = self.build_cluster_key([raw_market_id])
        cluster = self._session.query(EventIdentityCluster).filter_by(cluster_key=cluster_key).first()
        if cluster is not None:
            return cluster

        cluster = EventIdentityCluster(
            cluster_key=cluster_key,
            identity_type=IdentityType.SAME_EVENT.value,
            primary_canonical_event_id=canonical_event_id,
            confidence=1.0,
            confidence_version=_SCORER_VERSION,
            status="active",
            provenance={"created_by": "system", "reason": "singleton_init"},
        )
        self._session.add(cluster)
        self._session.flush()
        self._session.add(
            IdentityClusterMember(
                cluster_id=cluster.id,
                canonical_event_id=canonical_event_id,
                raw_market_id=raw_market_id,
                member_role="primary",
                added_by="system",
                evidence={"reason": "singleton_init"},
            )
        )
        self._session.flush()
        return cluster

    def find_best_cluster_match(
        self,
        market,
        candidate_clusters: list[EventIdentityCluster],
    ) -> ClusterDecision | None:
        best: ClusterDecision | None = None
        for cluster in candidate_clusters:
            primary_member = (
                self._session.query(IdentityClusterMember)
                .filter_by(cluster_id=cluster.id, member_role="primary")
                .first()
            )
            if primary_member is None or not primary_member.raw_market_id:
                continue
            primary_market = self._session.get(RawMarket, primary_member.raw_market_id)
            if primary_market is None:
                continue
            signals = self.score_pair(market, primary_market)
            if signals["score"] < _MIN_CLUSTER_CONFIDENCE:
                continue
            identity_type = self.classify_pair(market, primary_market)
            decision = ClusterDecision(
                cluster_id=cluster.id,
                identity_type=identity_type,
                confidence=signals["score"],
                provenance={
                    **signals,
                    "scorer_version": _SCORER_VERSION,
                    "embedding_version": "semantic-v1",
                    "compared_to_market_id": primary_market.id,
                },
            )
            if best is None or decision.confidence > best.confidence:
                best = decision
        return best

    def add_member_to_cluster(
        self,
        cluster_id: uuid.UUID,
        canonical_event_id: uuid.UUID,
        raw_market_id: str,
        *,
        evidence: dict,
        role: str = "secondary",
    ) -> IdentityClusterMember:
        existing = (
            self._session.query(IdentityClusterMember)
            .filter_by(cluster_id=cluster_id, canonical_event_id=canonical_event_id)
            .first()
        )
        if existing is not None:
            return existing
        member = IdentityClusterMember(
            cluster_id=cluster_id,
            canonical_event_id=canonical_event_id,
            raw_market_id=raw_market_id,
            member_role=role,
            added_by="system",
            evidence=evidence,
        )
        self._session.add(member)
        self._session.flush()
        return member

    @staticmethod
    def build_cluster_key(market_ids: list[str]) -> str:
        sorted_ids = sorted(market_ids)
        raw = "|".join(sorted_ids)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
        if len(sorted_ids) == 1:
            return f"cluster:{digest}:{sorted_ids[0]}"
        return f"cluster:{digest}"

    @staticmethod
    def _deadline_delta_hours(a, b) -> float:
        if a is None or b is None:
            return 9999.0
        return abs((a - b).total_seconds()) / 3600

    def _oracle_mismatch(self, market_a, market_b) -> bool:
        if not market_a.resolution_source or not market_b.resolution_source:
            return False
        return self._source_n.normalize(market_a.resolution_source) != self._source_n.normalize(
            market_b.resolution_source
        )

    @staticmethod
    def _source_mismatch(market_a, market_b) -> bool:
        return market_a.platform != market_b.platform

    def _subset_flags(self, title_a: str, title_b: str) -> tuple[bool, bool]:
        tokens_a = self._entity_n.token_set(title_a)
        tokens_b = self._entity_n.token_set(title_b)
        if not tokens_a or not tokens_b:
            return False, False
        if tokens_a < tokens_b:
            return True, False
        if tokens_b < tokens_a:
            return False, True
        return False, False
