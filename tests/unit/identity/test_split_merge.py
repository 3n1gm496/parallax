from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from parallax.identity.split_merge import SplitMergeService


def _make_cluster(status="active", identity_type="same_event"):
    cluster = MagicMock()
    cluster.id = uuid.uuid4()
    cluster.status = status
    cluster.identity_type = identity_type
    cluster.provenance = {}
    cluster.confidence = 0.8
    cluster.primary_canonical_event_id = uuid.uuid4()
    return cluster


class TestSplitMergeService:
    def setup_method(self):
        self.session = MagicMock()
        self.svc = SplitMergeService(self.session)

    def test_split_raises_if_cluster_not_found(self):
        self.session.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            self.svc.split_cluster(
                uuid.uuid4(),
                split_a_member_ids=["polymarket:a"],
                split_b_member_ids=["kalshi:b"],
                reason="test",
                triggered_by="tester",
            )

    def test_split_raises_if_cluster_not_active(self):
        self.session.get.return_value = _make_cluster(status="merged_into")
        with pytest.raises(ValueError, match="active"):
            self.svc.split_cluster(
                uuid.uuid4(),
                split_a_member_ids=["polymarket:a"],
                split_b_member_ids=["kalshi:b"],
                reason="test",
                triggered_by="tester",
            )

    def test_merge_raises_if_fewer_than_2_clusters(self):
        with pytest.raises(ValueError, match="two"):
            self.svc.merge_clusters([uuid.uuid4()], reason="test", triggered_by="tester")

    def test_merge_raises_if_cluster_not_found(self):
        self.session.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            self.svc.merge_clusters([uuid.uuid4(), uuid.uuid4()], reason="test", triggered_by="tester")
