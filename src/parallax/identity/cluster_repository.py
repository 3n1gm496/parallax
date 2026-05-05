from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from parallax.db.models import (
    EventIdentityCluster,
    IdentityBenchmarkCase,
    IdentityClusterMember,
    IdentityMetric,
    IdentityReviewActionRecord,
    IdentitySplitMergeHistory,
    IdentityTrainingExample,
)


@dataclass(slots=True)
class ClusterMetrics:
    false_merge_count: int
    false_split_count: int
    unresolved_rate: float
    ambiguous_rate: float
    verified_cluster_count: int
    benchmark_accuracy: float | None


class IdentityClusterRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_cluster(self, cluster_id: uuid.UUID) -> EventIdentityCluster | None:
        return self._session.get(EventIdentityCluster, cluster_id)

    def list_clusters(self, *, limit: int = 100) -> list[EventIdentityCluster]:
        return (
            self._session.query(EventIdentityCluster)
            .order_by(EventIdentityCluster.updated_at.desc(), EventIdentityCluster.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_members(self, cluster_id: uuid.UUID) -> list[IdentityClusterMember]:
        return (
            self._session.query(IdentityClusterMember)
            .filter_by(cluster_id=cluster_id)
            .order_by(IdentityClusterMember.added_at.asc())
            .all()
        )

    def get_cluster_ids_for_markets(self, market_ids: list[str]) -> list[str]:
        if not market_ids:
            return []
        rows = (
            self._session.query(IdentityClusterMember.cluster_id)
            .filter(IdentityClusterMember.raw_market_id.in_(market_ids))
            .distinct()
            .all()
        )
        return [str(cluster_id) for (cluster_id,) in rows]

    def get_cluster_for_market(self, market_id: str) -> EventIdentityCluster | None:
        member = (
            self._session.query(IdentityClusterMember)
            .filter_by(raw_market_id=market_id)
            .order_by(IdentityClusterMember.added_at.desc())
            .first()
        )
        if member is None:
            return None
        return self._session.get(EventIdentityCluster, member.cluster_id)

    def add_member(
        self,
        *,
        cluster_id: uuid.UUID,
        canonical_event_id: uuid.UUID,
        raw_market_id: str | None,
        member_role: str,
        added_by: str,
        evidence: dict,
    ) -> IdentityClusterMember:
        existing = (
            self._session.query(IdentityClusterMember)
            .filter_by(cluster_id=cluster_id, canonical_event_id=canonical_event_id)
            .first()
        )
        if existing is not None:
            existing.evidence = evidence
            return existing
        row = IdentityClusterMember(
            cluster_id=cluster_id,
            canonical_event_id=canonical_event_id,
            raw_market_id=raw_market_id,
            member_role=member_role,
            added_by=added_by,
            evidence=evidence,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def remove_member(self, cluster_id: uuid.UUID, raw_market_id: str) -> bool:
        row = (
            self._session.query(IdentityClusterMember)
            .filter_by(cluster_id=cluster_id, raw_market_id=raw_market_id)
            .first()
        )
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def record_review_action(
        self,
        *,
        cluster_id: uuid.UUID,
        action: str,
        reviewer: str,
        reason: str | None,
        evidence: dict | None = None,
    ) -> IdentityReviewActionRecord:
        row = IdentityReviewActionRecord(
            cluster_id=cluster_id,
            action=action,
            reviewer=reviewer,
            reason=reason,
            evidence=evidence or {},
            acted_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_review_actions(self, cluster_id: uuid.UUID) -> list[IdentityReviewActionRecord]:
        return (
            self._session.query(IdentityReviewActionRecord)
            .filter_by(cluster_id=cluster_id)
            .order_by(IdentityReviewActionRecord.acted_at.desc())
            .all()
        )

    def add_training_example(
        self,
        *,
        market_id_a: str,
        market_id_b: str,
        label: str,
        identity_type: str | None,
        labeler: str,
        notes: str | None = None,
    ) -> IdentityTrainingExample:
        row = (
            self._session.query(IdentityTrainingExample)
            .filter_by(market_id_a=market_id_a, market_id_b=market_id_b)
            .first()
        )
        if row is None:
            row = IdentityTrainingExample(
                market_id_a=market_id_a,
                market_id_b=market_id_b,
                label=label,
                identity_type=identity_type,
                labeler=labeler,
                notes=notes,
            )
            self._session.add(row)
        else:
            row.label = label
            row.identity_type = identity_type
            row.labeler = labeler
            row.notes = notes
        self._session.flush()
        return row

    def add_benchmark_case(
        self,
        *,
        case_key: str,
        market_id_a: str,
        market_id_b: str,
        expected_label: str,
        expected_identity_type: str,
        difficulty: str = "medium",
        notes: str | None = None,
    ) -> IdentityBenchmarkCase:
        row = self._session.query(IdentityBenchmarkCase).filter_by(case_key=case_key).first()
        if row is None:
            row = IdentityBenchmarkCase(
                case_key=case_key,
                market_id_a=market_id_a,
                market_id_b=market_id_b,
                expected_label=expected_label,
                expected_identity_type=expected_identity_type,
                difficulty=difficulty,
                notes=notes,
            )
            self._session.add(row)
        else:
            row.market_id_a = market_id_a
            row.market_id_b = market_id_b
            row.expected_label = expected_label
            row.expected_identity_type = expected_identity_type
            row.difficulty = difficulty
            row.notes = notes
        self._session.flush()
        return row

    def list_split_merge_history(self, *, limit: int = 100) -> list[IdentitySplitMergeHistory]:
        return (
            self._session.query(IdentitySplitMergeHistory)
            .order_by(IdentitySplitMergeHistory.acted_at.desc())
            .limit(limit)
            .all()
        )

    def metrics_snapshot(self) -> ClusterMetrics:
        latest_metric = self._session.query(IdentityMetric).order_by(IdentityMetric.computed_at.desc()).first()
        total_clusters = self._session.query(func.count(EventIdentityCluster.id)).scalar() or 0
        verified_cluster_count = (
            self._session.query(func.count(EventIdentityCluster.id))
            .filter(EventIdentityCluster.status == "active", EventIdentityCluster.confidence >= 0.75)
            .scalar()
            or 0
        )
        ambiguous_count = (
            self._session.query(func.count(EventIdentityCluster.id))
            .filter(EventIdentityCluster.status == "active", EventIdentityCluster.confidence < 0.75)
            .scalar()
            or 0
        )
        unresolved_count = (
            self._session.query(func.count(EventIdentityCluster.id))
            .filter(EventIdentityCluster.status != "active")
            .scalar()
            or 0
        )
        return ClusterMetrics(
            false_merge_count=int(getattr(latest_metric, "false_merge_count", 0) or 0),
            false_split_count=int(getattr(latest_metric, "false_split_count", 0) or 0),
            unresolved_rate=round(unresolved_count / max(total_clusters, 1), 4) if total_clusters else 0.0,
            ambiguous_rate=round(ambiguous_count / max(total_clusters, 1), 4) if total_clusters else 0.0,
            verified_cluster_count=int(verified_cluster_count),
            benchmark_accuracy=getattr(latest_metric, "benchmark_accuracy", None),
        )
