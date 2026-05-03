from __future__ import annotations

from datetime import datetime, timezone

from parallax.db.models import CanonicalEvent, EventIdentityCluster, IdentityClusterMember, RawMarket
from parallax.identity.cluster_engine import ClusterEngine
from parallax.identity.split_merge import SplitMergeService
from parallax.shared.schemas import IdentityType


class TestClusterEngineIntegration:
    def test_find_or_create_singleton_cluster(self, test_session):
        event = CanonicalEvent(name="Test Event", domain="politics")
        test_session.add(event)
        test_session.flush()

        market = RawMarket(
            id="polymarket:test-v3",
            platform="polymarket",
            market_id="test-v3",
            title="Will inflation exceed 5%?",
            description="",
            resolution_criteria="",
            outcomes=["Yes", "No"],
            outcome_prices=[0.5, 0.5],
            category="politics",
            group_id=None,
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            is_closed=False,
            resolution_source=None,
            raw_payload={},
        )
        test_session.add(market)
        test_session.flush()

        cluster = ClusterEngine(test_session).find_or_create_singleton_cluster(event.id, market.id)
        assert cluster.id is not None
        assert cluster.status == "active"
        assert cluster.identity_type == IdentityType.SAME_EVENT.value
        assert test_session.query(IdentityClusterMember).filter_by(cluster_id=cluster.id).count() == 1

    def test_find_or_create_is_idempotent(self, test_session):
        event = CanonicalEvent(name="Idempotent Test", domain="economics")
        test_session.add(event)
        test_session.flush()
        market = RawMarket(
            id="polymarket:idempotent-v3",
            platform="polymarket",
            market_id="idempotent-v3",
            title="Idempotent market?",
            description="",
            resolution_criteria="",
            outcomes=["Yes", "No"],
            outcome_prices=[0.5, 0.5],
            category="economics",
            group_id=None,
            deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
            is_closed=False,
            resolution_source=None,
            raw_payload={},
        )
        test_session.add(market)
        test_session.flush()

        engine = ClusterEngine(test_session)
        assert engine.find_or_create_singleton_cluster(event.id, market.id).id == engine.find_or_create_singleton_cluster(
            event.id, market.id
        ).id


class TestSplitMergeIntegration:
    def test_split_cluster_creates_two_halves(self, test_session):
        event = CanonicalEvent(name="Split Test", domain="politics")
        test_session.add(event)
        test_session.flush()
        test_session.add_all(
            [
                RawMarket(
                    id="polymarket:split-a",
                    platform="polymarket",
                    market_id="split-a",
                    title="Market A",
                    description="",
                    resolution_criteria="",
                    outcomes=["Yes", "No"],
                    outcome_prices=[0.5, 0.5],
                    category="politics",
                    group_id=None,
                    deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
                    is_closed=False,
                    resolution_source=None,
                    raw_payload={},
                ),
                RawMarket(
                    id="kalshi:split-b",
                    platform="kalshi",
                    market_id="split-b",
                    title="Market B",
                    description="",
                    resolution_criteria="",
                    outcomes=["Yes", "No"],
                    outcome_prices=[0.5, 0.5],
                    category="politics",
                    group_id=None,
                    deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
                    is_closed=False,
                    resolution_source=None,
                    raw_payload={},
                ),
            ]
        )
        test_session.flush()

        cluster = EventIdentityCluster(
            cluster_key="cluster:split-test",
            identity_type="same_event",
            primary_canonical_event_id=event.id,
            confidence=0.8,
            status="active",
            provenance={},
        )
        test_session.add(cluster)
        test_session.flush()
        test_session.add_all(
            [
                IdentityClusterMember(
                    cluster_id=cluster.id,
                    canonical_event_id=event.id,
                    raw_market_id="polymarket:split-a",
                    member_role="primary",
                    added_by="test",
                    evidence={},
                ),
                IdentityClusterMember(
                    cluster_id=cluster.id,
                    canonical_event_id=event.id,
                    raw_market_id="kalshi:split-b",
                    member_role="secondary",
                    added_by="test",
                    evidence={},
                ),
            ]
        )
        test_session.flush()

        cluster_a, cluster_b = SplitMergeService(test_session).split_cluster(
            cluster.id,
            split_a_member_ids=["polymarket:split-a"],
            split_b_member_ids=["kalshi:split-b"],
            reason="test split",
            triggered_by="tester",
        )
        test_session.refresh(cluster)
        assert cluster.status == "split"
        assert cluster_a.id != cluster_b.id

    def test_merge_two_clusters(self, test_session):
        event = CanonicalEvent(name="Merge Test", domain="economics")
        test_session.add(event)
        test_session.flush()
        for suffix in ["merge-x", "merge-y"]:
            test_session.add(
                RawMarket(
                    id=f"polymarket:{suffix}",
                    platform="polymarket",
                    market_id=suffix,
                    title=f"Market {suffix}",
                    description="",
                    resolution_criteria="",
                    outcomes=["Yes", "No"],
                    outcome_prices=[0.5, 0.5],
                    category="economics",
                    group_id=None,
                    deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
                    is_closed=False,
                    resolution_source=None,
                    raw_payload={},
                )
            )
        test_session.flush()

        clusters = []
        for suffix in ["merge-x", "merge-y"]:
            cluster = EventIdentityCluster(
                cluster_key=f"cluster:{suffix}",
                identity_type="near_duplicate",
                primary_canonical_event_id=event.id,
                confidence=0.7,
                status="active",
                provenance={},
            )
            test_session.add(cluster)
            test_session.flush()
            test_session.add(
                IdentityClusterMember(
                    cluster_id=cluster.id,
                    canonical_event_id=event.id,
                    raw_market_id=f"polymarket:{suffix}",
                    member_role="primary",
                    added_by="test",
                    evidence={},
                )
            )
            clusters.append(cluster)
        test_session.flush()

        merged = SplitMergeService(test_session).merge_clusters(
            [cluster.id for cluster in clusters],
            reason="confirmed same event",
            triggered_by="tester",
        )
        assert merged.status == "active"
        for cluster in clusters:
            test_session.refresh(cluster)
            assert cluster.status == "merged_into"
