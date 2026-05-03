from __future__ import annotations

import pytest

from parallax.identity.embedding_provider import EmbeddingProvider, TokenVectorProvider


class TestTokenVectorProvider:
    def setup_method(self):
        self.p = TokenVectorProvider()

    def test_implements_provider(self):
        assert isinstance(self.p, EmbeddingProvider)

    def test_identical_texts_score_1(self):
        assert self.p.similarity("us inflation 2026", "us inflation 2026") == pytest.approx(1.0, abs=0.01)

    def test_disjoint_texts_score_0(self):
        assert self.p.similarity("football championship", "interest rate decision") == pytest.approx(0.0, abs=0.01)

    def test_partial_overlap(self):
        score = self.p.similarity(
            "will us inflation exceed 5 percent",
            "us inflation above 5 percent by december",
        )
        assert 0.3 < score < 0.95

    def test_empty_string_returns_0(self):
        assert self.p.similarity("", "some text") == 0.0
        assert self.p.similarity("some text", "") == 0.0

    def test_version_is_string(self):
        assert isinstance(self.p.version, str)
        assert len(self.p.version) > 0

    def test_symmetric(self):
        a = "will the fed raise rates in 2026"
        b = "federal reserve rate hike 2026"
        assert self.p.similarity(a, b) == self.p.similarity(b, a)
