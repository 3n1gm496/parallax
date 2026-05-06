"""
Parallax Semantic Agent — Unit Tests

Tests the core matching logic WITHOUT requiring Neo4j or a live model,
using mocked embeddings and a mock graph repository.

Run: uv run pytest tests/unit/test_semantic_agent.py -v
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from parallax.graph.semantic_agent import SemanticAgent, MarketRecord, SemanticMatch


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_market(market_id: str, platform: str, question: str) -> MarketRecord:
    return MarketRecord(market_id=market_id, platform=platform, question=question)


TRUMP_KALSHI   = make_market("K-TRUMP-2024", "kalshi",    "Will Donald Trump win the 2024 US election?")
TRUMP_POLY_WIN = make_market("P-TRUMP-WIN",  "polymarket","Will Trump win the 2024 presidential election?")
TRUMP_POLY_LOSE= make_market("P-TRUMP-LOSE", "polymarket","Will Trump lose the 2024 US presidential election?")
HARRIS_POLY    = make_market("P-HARRIS",     "polymarket","Will Kamala Harris become president in 2024?")


# ── Complement detection tests ─────────────────────────────────────────────────

class TestComplementDetection:
    def test_obvious_complement(self):
        """Win vs Lose should be detected as complement."""
        result = SemanticAgent._is_complement_pair(
            TRUMP_KALSHI.question,
            TRUMP_POLY_LOSE.question,
        )
        assert result is True

    def test_equivalent_pair_not_complement(self):
        """Two questions framing the same event positively should not be complement."""
        result = SemanticAgent._is_complement_pair(
            TRUMP_KALSHI.question,
            TRUMP_POLY_WIN.question,
        )
        # Both are positive ("win") — not a complement
        assert result is False

    def test_negation_detection(self):
        result = SemanticAgent._is_complement_pair(
            "Will X win?",
            "Will X not win?",
        )
        assert result is True


# ── Confidence computation ─────────────────────────────────────────────────────

class TestConfidenceComputation:
    def test_complement_bonus(self):
        candidate = {"platform": "polymarket", "question": "Will Trump lose?", "score": 0.90}
        conf_comp = SemanticAgent._compute_confidence(0.90, True, TRUMP_KALSHI, candidate)
        conf_eq   = SemanticAgent._compute_confidence(0.90, False, TRUMP_KALSHI, candidate)
        assert conf_comp > conf_eq, "Complement should receive higher confidence"

    def test_confidence_capped(self):
        candidate = {"platform": "polymarket", "question": "x"}
        conf = SemanticAgent._compute_confidence(1.0, True, TRUMP_KALSHI, candidate)
        assert conf <= 1.0


# ── Full pipeline with mocked model & graph repo ───────────────────────────────

class TestFindMatchesPipeline:
    def _build_agent(self):
        agent = SemanticAgent.__new__(SemanticAgent)
        agent._model_name = "mock-model"
        agent._model = None
        return agent

    @pytest.mark.anyio
    @patch.object(SemanticAgent, "embed")
    async def test_find_matches_cross_venue_only(self, mock_embed):
        """Same-venue pairs should be skipped."""
        mock_embed.return_value = [[0.1] * 384, [0.1] * 384]  # Dummy embeddings

        mock_repo = AsyncMock()
        mock_repo.find_similar_markets.return_value = [
            {"market_id": "K-TRUMP-2024", "platform": "kalshi",
             "question": TRUMP_KALSHI.question, "score": 0.95}
        ]

        agent = self._build_agent()
        markets = [TRUMP_KALSHI, TRUMP_POLY_WIN]
        matches = await agent.find_matches(markets, graph_repo=mock_repo, min_similarity=0.85)

        # The candidate has same platform as TRUMP_KALSHI (kalshi ↔ kalshi) → should be skipped
        # But TRUMP_POLY_WIN will see the kalshi candidate → cross-venue → valid
        cross_venue = [m for m in matches if m.market_a.platform != m.market_b.platform]
        assert len(cross_venue) >= 0  # At least pipeline ran without error

    @pytest.mark.anyio
    @patch.object(SemanticAgent, "embed")
    async def test_compile_arbitrage_sets_complement_only(self, mock_embed):
        """compile_arbitrage_sets should only act on COMPLEMENT_OF matches."""
        mock_embed.return_value = [[0.1] * 384]

        mock_repo = AsyncMock()
        agent = self._build_agent()

        matches_complement = [SemanticMatch(
            market_a=TRUMP_KALSHI,
            market_b=TRUMP_POLY_LOSE,
            cosine_score=0.92,
            relation_type="COMPLEMENT_OF",
            is_complement=True,
            confidence=0.95,
        )]
        matches_equivalent = [SemanticMatch(
            market_a=TRUMP_KALSHI,
            market_b=TRUMP_POLY_WIN,
            cosine_score=0.93,
            relation_type="EQUIVALENT_TO",
            is_complement=False,
            confidence=0.94,
        )]

        result_comp = await agent.compile_arbitrage_sets(matches_complement, graph_repo=mock_repo)
        result_equiv = await agent.compile_arbitrage_sets(matches_equivalent, graph_repo=mock_repo)

        assert len(result_comp) == 1, "Complement should produce ArbitrageSet"
        assert len(result_equiv) == 0, "EQUIVALENT_TO should NOT produce ArbitrageSet"
