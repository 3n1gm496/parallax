from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from parallax.pipeline.runner import PipelineRunner
from parallax.shared.schemas import RunSummary


class TestPipelineRunner:
    def _make_runner(self, session):
        @contextmanager
        def factory():
            yield session

        return PipelineRunner(factory)

    @pytest.mark.anyio
    async def test_run_once_returns_summary(self):
        session = MagicMock()
        session.commit = MagicMock()

        with patch("parallax.pipeline.runner.MarketRepository") as MockMarket, \
             patch("parallax.pipeline.runner.PostgresGraphRepository"), \
             patch("parallax.pipeline.runner.AuditService"), \
             patch("parallax.pipeline.runner.ProverService") as MockProver, \
             patch("parallax.pipeline.runner.DivergenceService") as MockDivergence, \
             patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates, \
             patch("parallax.pipeline.runner.CourtService"), \
             patch("parallax.pipeline.runner.SimulatorService"), \
             patch("parallax.pipeline.runner.CompilerService") as MockCompiler, \
             patch("parallax.pipeline.runner.AnthropicCompilerProvider"), \
             patch("parallax.pipeline.runner.Stage2LLMDetector"):

            MockMarket.return_value.list_open.return_value = []
            MockProver.return_value.run = AsyncMock(return_value=3)
            MockDivergence.return_value.scan.return_value = 2
            MockCandidates.return_value.list_open.return_value = []
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())

            runner = self._make_runner(session)
            summary = await runner.run_once()

        assert isinstance(summary, RunSummary)
        assert summary.relations_detected == 3
        assert summary.candidates_found == 2
        assert summary.errors == []

    @pytest.mark.anyio
    async def test_run_once_captures_errors(self):
        session = MagicMock()

        with patch("parallax.pipeline.runner.MarketRepository") as MockMarket, \
             patch("parallax.pipeline.runner.PostgresGraphRepository"), \
             patch("parallax.pipeline.runner.AuditService"), \
             patch("parallax.pipeline.runner.ProverService") as MockProver, \
             patch("parallax.pipeline.runner.DivergenceService") as MockDivergence, \
             patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates, \
             patch("parallax.pipeline.runner.CourtService"), \
             patch("parallax.pipeline.runner.SimulatorService"), \
             patch("parallax.pipeline.runner.CompilerService") as MockCompiler, \
             patch("parallax.pipeline.runner.AnthropicCompilerProvider"), \
             patch("parallax.pipeline.runner.Stage2LLMDetector"):

            MockMarket.return_value.list_open.return_value = []
            MockProver.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())

            runner = self._make_runner(session)
            summary = await runner.run_once()

        assert len(summary.errors) == 1
        assert "boom" in summary.errors[0]
