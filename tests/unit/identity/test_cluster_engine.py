from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from parallax.identity.cluster_engine import ClusterEngine
from parallax.identity.embedding_provider import TokenVectorProvider
from parallax.shared.schemas import IdentityType


def _make_market(
    id="polymarket:abc",
    platform="polymarket",
    title="Will US inflation exceed 5% in 2026?",
    group_id=None,
    deadline=None,
    resolution_source=None,
):
    market = MagicMock()
    market.id = id
    market.platform = platform
    market.title = title
    market.group_id = group_id
    market.deadline = deadline or datetime(2026, 12, 31, tzinfo=timezone.utc)
    market.resolution_source = resolution_source
    return market


class TestClusterEngine:
    def setup_method(self):
        self.session = MagicMock()
        self.engine = ClusterEngine(self.session, embedding_provider=TokenVectorProvider())

    def test_score_pair_identical_titles_high(self):
        result = self.engine.score_pair(_make_market(), _make_market(id="kalshi:xyz", platform="kalshi"))
        assert result["score"] >= 0.8

    def test_score_pair_disjoint_titles_low(self):
        result = self.engine.score_pair(
            _make_market(title="Will the 2026 World Cup final be held in Mexico?"),
            _make_market(id="kalshi:xyz", title="Federal Reserve interest rate decision Q4 2026"),
        )
        assert result["score"] < 0.3

    def test_score_pair_group_id_match_is_1(self):
        result = self.engine.score_pair(
            _make_market(group_id="g1"),
            _make_market(id="kalshi:xyz", group_id="g1"),
        )
        assert result["score"] == 1.0
        assert result["platform_group_match"] is True

    def test_classify_pair_returns_identity_type(self):
        result = self.engine.classify_pair(_make_market(), _make_market(id="kalshi:xyz", platform="kalshi"))
        assert isinstance(result, IdentityType)

    def test_build_cluster_key_is_deterministic(self):
        assert ClusterEngine.build_cluster_key(["polymarket:abc", "kalshi:xyz"]) == ClusterEngine.build_cluster_key(
            ["kalshi:xyz", "polymarket:abc"]
        )

    def test_build_cluster_key_single_market(self):
        key = ClusterEngine.build_cluster_key(["polymarket:abc"])
        assert "polymarket:abc" in key
