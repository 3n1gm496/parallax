from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.db.models import EventIdentityCluster, IdentityClusterMember, IdentitySplitMergeHistory
from parallax.identity.cluster_engine import ClusterEngine


class SplitMergeService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def split_cluster(
        self,
        cluster_id: uuid.UUID,
        *,
        split_a_member_ids: list[str],
        split_b_member_ids: list[str],
        reason: str,
        triggered_by: str,
        evidence: dict | None = None,
    ) -> tuple[EventIdentityCluster, EventIdentityCluster]:
        cluster = self._session.get(EventIdentityCluster, cluster_id)
        if cluster is None:
            raise ValueError(f"Cluster {cluster_id} not found")
        if cluster.status != "active":
            raise ValueError(f"Cluster {cluster_id} is not active (status={cluster.status})")

        cluster.status = "split"
        cluster.updated_at = datetime.now(timezone.utc)
        cluster_a = self._create_split_half(cluster, split_a_member_ids, suffix="a")
        cluster_b = self._create_split_half(cluster, split_b_member_ids, suffix="b")
        self._session.add(
            IdentitySplitMergeHistory(
                action="split",
                source_cluster_ids=[str(cluster_id)],
                target_cluster_ids=[str(cluster_a.id), str(cluster_b.id)],
                triggered_by=triggered_by,
                reason=reason,
                evidence=evidence or {},
                acted_at=datetime.now(timezone.utc),
            )
        )
        self._session.flush()
        return cluster_a, cluster_b

    def merge_clusters(
        self,
        source_ids: list[uuid.UUID],
        *,
        reason: str,
        triggered_by: str,
        identity_type: str = "same_event",
        evidence: dict | None = None,
    ) -> EventIdentityCluster:
        if len(source_ids) < 2:
            raise ValueError("Merge requires at least two source clusters")
        sources: list[EventIdentityCluster] = []
        member_raw_ids: list[str] = []
        for source_id in source_ids:
            cluster = self._session.get(EventIdentityCluster, source_id)
            if cluster is None:
                raise ValueError(f"Cluster {source_id} not found")
            sources.append(cluster)
            members = self._session.query(IdentityClusterMember).filter_by(cluster_id=cluster.id).all()
            member_raw_ids.extend([member.raw_market_id for member in members if member.raw_market_id])

        merged = EventIdentityCluster(
            cluster_key=ClusterEngine.build_cluster_key(member_raw_ids or [str(source_id) for source_id in source_ids]),
            identity_type=identity_type,
            primary_canonical_event_id=sources[0].primary_canonical_event_id,
            confidence=min(source.confidence for source in sources),
            confidence_version="identity-v3",
            status="active",
            provenance={"merged_from": [str(source.id) for source in sources], "reason": reason},
        )
        self._session.add(merged)
        self._session.flush()

        for source in sources:
            members = self._session.query(IdentityClusterMember).filter_by(cluster_id=source.id).all()
            for member in members:
                exists = (
                    self._session.query(IdentityClusterMember)
                    .filter_by(cluster_id=merged.id, canonical_event_id=member.canonical_event_id)
                    .first()
                )
                if exists is None:
                    self._session.add(
                        IdentityClusterMember(
                            cluster_id=merged.id,
                            canonical_event_id=member.canonical_event_id,
                            raw_market_id=member.raw_market_id,
                            member_role=member.member_role,
                            added_by=triggered_by,
                            evidence={"merged_from_cluster": str(source.id)},
                        )
                    )
            source.status = "merged_into"
            source.updated_at = datetime.now(timezone.utc)

        self._session.add(
            IdentitySplitMergeHistory(
                action="merge",
                source_cluster_ids=[str(source.id) for source in sources],
                target_cluster_ids=[str(merged.id)],
                triggered_by=triggered_by,
                reason=reason,
                evidence=evidence or {},
                acted_at=datetime.now(timezone.utc),
            )
        )
        self._session.flush()
        return merged

    def _create_split_half(self, source: EventIdentityCluster, member_raw_ids: list[str], suffix: str) -> EventIdentityCluster:
        half = EventIdentityCluster(
            cluster_key=f"{ClusterEngine.build_cluster_key(member_raw_ids)}:{suffix}",
            identity_type=source.identity_type,
            primary_canonical_event_id=source.primary_canonical_event_id,
            confidence=source.confidence,
            confidence_version="identity-v3",
            status="active",
            provenance={"split_from": str(source.id), "half": suffix},
        )
        self._session.add(half)
        self._session.flush()
        for raw_market_id in member_raw_ids:
            original = (
                self._session.query(IdentityClusterMember)
                .filter_by(cluster_id=source.id, raw_market_id=raw_market_id)
                .first()
            )
            if original is not None:
                self._session.add(
                    IdentityClusterMember(
                        cluster_id=half.id,
                        canonical_event_id=original.canonical_event_id,
                        raw_market_id=original.raw_market_id,
                        member_role=original.member_role,
                        added_by="system:split",
                        evidence={"split_from": str(source.id)},
                    )
                )
        self._session.flush()
        return half
