from __future__ import annotations

from datetime import datetime, timezone

from parallax.identity.normalizer import DeadlineNormalizer, EntityNormalizer, SourceNormalizer


class TestEntityNormalizer:
    def setup_method(self):
        self.n = EntityNormalizer()

    def test_normalize_strips_stopwords(self):
        result = self.n.normalize("Will the US economy grow in 2026?")
        assert "will" not in result
        assert "the" not in result
        assert "in" not in result
        assert "us" in result or "economy" in result

    def test_normalize_lowercases(self):
        result = self.n.normalize("Federal Reserve Interest Rates")
        assert result == result.lower()

    def test_normalize_is_deterministic(self):
        assert self.n.normalize("Who will win the 2026 US election?") == self.n.normalize(
            "Who will win the 2026 US election?"
        )

    def test_normalize_sorts_tokens(self):
        assert self.n.normalize("inflation US 2026") == self.n.normalize("2026 US inflation")

    def test_token_set_extracts_meaningful_tokens(self):
        tokens = self.n.token_set("US inflation rises above 5%")
        assert "inflation" in tokens
        assert "rises" in tokens
        assert "above" not in tokens or "5" in tokens

    def test_jaccard_identical(self):
        assert self.n.jaccard("Will US inflation exceed 5% in 2026?", "Will US inflation exceed 5% in 2026?") == 1.0

    def test_jaccard_disjoint(self):
        assert self.n.jaccard("football world cup 2026", "federal reserve interest rate") < 0.1

    def test_jaccard_partial_overlap(self):
        score = self.n.jaccard("Will US inflation rise in 2026?", "US inflation exceeds 4% by end of 2026?")
        assert 0.2 < score < 0.9


class TestSourceNormalizer:
    def setup_method(self):
        self.n = SourceNormalizer()

    def test_normalize_empty_returns_empty(self):
        assert self.n.normalize(None) == ""
        assert self.n.normalize("") == ""

    def test_normalize_known_alias(self):
        assert self.n.normalize("Associated Press") == "ap"
        assert self.n.normalize("reuters news") == "reuters"
        assert self.n.normalize("Polymarket") == "polymarket"

    def test_normalize_unknown_source(self):
        result = self.n.normalize("Some Custom Oracle LLC")
        assert isinstance(result, str)
        assert len(result) > 0
        assert " " not in result

    def test_same_source_normalizes_consistently(self):
        assert self.n.normalize("Associated Press") == self.n.normalize("Associated Press")


class TestDeadlineNormalizer:
    def setup_method(self):
        self.n = DeadlineNormalizer()
        self.d = datetime(2026, 11, 3, 23, 59, tzinfo=timezone.utc)

    def test_normalize_returns_date_string(self):
        assert self.n.normalize(self.d) == "2026-11-03"

    def test_normalize_none_returns_unknown(self):
        assert self.n.normalize(None) == "unknown"

    def test_bucket_q4(self):
        assert self.n.bucket(self.d) == "2026-Q4"

    def test_bucket_q1(self):
        assert self.n.bucket(datetime(2026, 2, 14, tzinfo=timezone.utc)) == "2026-Q1"

    def test_compatible_within_24h(self):
        a = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 11, 3, 23, 0, tzinfo=timezone.utc)
        assert self.n.compatible(a, b, tolerance_hours=24) is True

    def test_compatible_outside_24h(self):
        a = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc)
        assert self.n.compatible(a, b, tolerance_hours=24) is False

    def test_compatible_none_deadline_is_false(self):
        assert self.n.compatible(None, self.d) is False
        assert self.n.compatible(self.d, None) is False
