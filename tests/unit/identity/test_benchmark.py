from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parallax.identity.benchmark import BenchmarkResult, BenchmarkRunner


class TestBenchmarkRunner:
    def setup_method(self):
        self.session = MagicMock()
        self.runner = BenchmarkRunner(self.session)

    def test_benchmark_result_accuracy_perfect(self):
        assert BenchmarkResult(total=5, correct=5, wrong=0, skipped=0, details=[]).accuracy == 1.0

    def test_benchmark_result_accuracy_zero(self):
        assert BenchmarkResult(total=5, correct=0, wrong=5, skipped=0, details=[]).accuracy == 0.0

    def test_benchmark_result_accuracy_partial(self):
        assert BenchmarkResult(total=10, correct=7, wrong=3, skipped=0, details=[]).accuracy == pytest.approx(0.7)

    def test_evaluate_empty_cases_returns_zero_total(self):
        self.session.query.return_value.all.return_value = []
        result = self.runner.evaluate_all()
        assert result.total == 0
        assert result.accuracy == 0.0
