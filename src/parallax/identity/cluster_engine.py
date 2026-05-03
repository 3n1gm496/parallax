from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from parallax.db.models import EventIdentityCluster, IdentityClusterMember, RawMarket
from parallax.identity.classifier import PairClassifier
from parallax.identity.embedding_provider import EmbeddingProvider, TokenVectorProvider
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
    def __init__(self, session: Session, embedding_provider: EmbeddingProvider | None = None) -> None:
        self._session = session
        self._embed = embedding_provider or TokenVectorProvider()
        self._classifier = PairClassifier()
        self._entity_n = EntityNormalizer()
        self._source_n = SourceNormalizer()
        self._deadline_n = DeadlineNormalizer()

    def score_pair(self, market_a, market_b) -> dict:
        platform_group_match = bool(
            market_a.group_id and market_b.group_id and market_a.group_id == market_b.group_id
        )
        if platform_group_match:
            return {
                "score": 1.0,
                "platform_group_match": True,
                "lexical_score": 1.0,
                "embedding_score": 1.0,
                "deadline_delta_hours": 0.0,
                "oracle_mismatch": False,
                "source_mismatch": False,
                "entity_overlap": 99,
                "predicate_match": True,
                "subset_signal": False,
                "superset_signal": False,
            }

        lexical = self._entity_n.jaccard(market_a.title, market_b.title)
        embedding = self._embed.similarity(market_a.title, market_b.title)
        deadline_delta = self._deadline_delta_hours(market_a.deadline, market_b.deadline)
        oracle_mismatch = self._oracle_mismatch(market_a, market_b)
        source_mismatch = self._source_mismatch(market_a, market_b)
        overlap_count = len(self._entity_n.token_set(market_a.title) & self._entity_n.token_set(market_b.title))
        subset_signal, superset_signal = self._subset_flags(market_a.title, market_b.title)
        score = round(
            0.35 * lexical
            + 0.35 * embedding
            + (0.15 if deadline_delta <= 24 else 0.0)
            + (0.075 if not oracle_mismatch else 0.0)
            + (0.05 if overlap_count >= 2 else 0.0)
            + (0.025 if not source_mismatch else 0.0),
            4,
        )
        if overlap_count <= 1 and lexical < 0.3 and embedding < 0.45:
            score = min(score, 0.29)
        return {
            "score": score,
            "platform_group_match": False,
            "lexical_score": lexical,
            "embedding_score": embedding,
            "deadline_delta_hours": deadline_delta,
            "oracle_mismatch": oracle_mismatch,
            "source_mismatch": source_mismatch,
            "entity_overlap": overlap_count,
            "predicate_match": lexical >= 0.5 or embedding >= 0.65,
            "subset_signal": subset_signal,
            "superset_signal": superset_signal,
        }

    def classify_pair(self, market_a, market_b) -> IdentityType:
        signals = self.score_pair(market_a, market_b)
        return self._classifier.classify(
            lexical_score=signals["lexical_score"],
            predicate_match=signals["predicate_match"],
            entity_overlap=signals["entity_overlap"],
            deadline_delta_hours=signals["deadline_delta_hours"],
            oracle_mismatch=signals["oracle_mismatch"],
            source_mismatch=signals["source_mismatch"],
            platform_group_match=signals["platform_group_match"],
            subset_signal=signals["subset_signal"],
            superset_signal=signals["superset_signal"],
            embedding_score=signals["embedding_score"],
        )

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
                    "embedding_version": self._embed.version,
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
