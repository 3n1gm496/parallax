from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from parallax.pipeline.runner import PipelineRunner
from parallax.shared.schemas import RunSummary


class TestPipelineRunner:
    def _make_runner(self, session):
        @contextmanager
        def factory():
            yield session

        return PipelineRunner(factory)

    def test_run_once_returns_summary(self):
        session = MagicMock()
        session.commit = MagicMock()

        with patch("parallax.pipeline.runner.MarketRepository") as MockMarket, \
             patch("parallax.pipeline.runner.PostgresGraphRepository"), \
             patch("parallax.pipeline.runner.AuditService"), \
             patch("parallax.pipeline.runner.ProverService") as MockProver, \
             patch("parallax.pipeline.runner.DivergenceService") as MockDivergence, \
             patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates, \
             patch("parallax.pipeline.runner.CourtService"), \
             patch("parallax.pipeline.runner.SimulatorService"):

            MockMarket.return_value.list_open.return_value = []
            MockProver.return_value.run.return_value = 3
            MockDivergence.return_value.scan.return_value = 2
            MockCandidates.return_value.list_open.return_value = []

            runner = self._make_runner(session)
            summary = runner.run_once()

        assert isinstance(summary, RunSummary)
        assert summary.relations_detected == 3
        assert summary.candidates_found == 2
        assert summary.errors == []

    def test_run_once_captures_errors(self):
        session = MagicMock()

        with patch("parallax.pipeline.runner.MarketRepository") as MockMarket, \
             patch("parallax.pipeline.runner.PostgresGraphRepository"), \
             patch("parallax.pipeline.runner.AuditService"), \
             patch("parallax.pipeline.runner.ProverService") as MockProver, \
             patch("parallax.pipeline.runner.DivergenceService") as MockDivergence, \
             patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates, \
             patch("parallax.pipeline.runner.CourtService"), \
             patch("parallax.pipeline.runner.SimulatorService"):

            MockMarket.return_value.list_open.return_value = []
            MockProver.return_value.run.side_effect = RuntimeError("boom")
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []

            runner = self._make_runner(session)
            summary = runner.run_once()

        assert len(summary.errors) == 1
        assert "boom" in summary.errors[0]
