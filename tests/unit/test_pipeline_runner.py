from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parallax.ops.schemas import RunSummary
from parallax.pipeline.runner import PipelineRunner, build_ingestion_adapters


class TestPipelineRunner:
    def _make_runner(self, session):
        @contextmanager
        def factory():
            yield session

        return PipelineRunner(factory)

    @staticmethod
    def _nested_tx():
        @contextmanager
        def nested():
            yield

        return nested()

    @pytest.mark.anyio
    async def test_run_once_returns_summary(self):
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService") as MockCourt,
            patch("parallax.pipeline.runner.TrackerService") as MockTracker,
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = []
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 2
            MockRelationService.return_value.run = AsyncMock(return_value=3)
            MockDivergence.return_value.scan.return_value = 2
            MockCandidates.return_value.list_open.return_value = []
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockCourt.return_value.evaluate.return_value = MagicMock(value="WATCHLIST")
            MockTracker.return_value.open_position.return_value = None
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 5, "kalshi": 4})

            summary = await self._make_runner(session).run_once()

        assert isinstance(summary, RunSummary)
        assert summary.markets_ingested == 9
        assert summary.market_counts_by_platform == {"polymarket": 5, "kalshi": 4}
        assert summary.events_resolved == 2
        assert summary.relations_detected == 3
        assert summary.candidates_found == 2
        assert summary.errors == []

    @pytest.mark.anyio
    async def test_run_once_skips_compile_without_anthropic_key(self):
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService") as MockAudit,
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService"),
            patch("parallax.pipeline.runner.TrackerService"),
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider") as MockProvider,
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer") as MockSemantic,
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
        ):
            mock_settings.anthropic_api_key = "placeholder"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = [MagicMock(id="pm:a")]
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 1, "kalshi": 0})

            summary = await self._make_runner(session).run_once()

        MockProvider.assert_not_called()
        MockCompiler.assert_not_called()
        MockSemantic.assert_not_called()
        compiler_call = next(
            call for call in MockAudit.return_value.record.call_args_list if call.args[0] == "pipeline.compiler.complete"
        )
        assert compiler_call.args[3]["compiler_mode"] == "disabled"
        assert summary.errors == []

    def test_build_ingestion_adapters_includes_both_native_providers(self):
        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.PolymarketAdapter") as MockPoly,
            patch("parallax.pipeline.runner.KalshiAdapter") as MockKalshi,
        ):
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 25
            mock_settings.pipeline_max_open_markets = 0
            MockPoly.return_value = MagicMock()
            MockKalshi.return_value = MagicMock()

            adapters = build_ingestion_adapters()

        assert adapters == [MockPoly.return_value, MockKalshi.return_value]
        MockPoly.assert_called_once_with(max_events=50)
        MockKalshi.assert_called_once_with(max_events=25)

    @pytest.mark.anyio
    async def test_run_once_honors_pipeline_max_open_markets(self):
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx
        markets = [MagicMock(id=f"pm:{idx}") for idx in range(5)]

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService"),
            patch("parallax.pipeline.runner.TrackerService"),
            patch("parallax.pipeline.runner.CompilerService"),
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
        ):
            mock_settings.anthropic_api_key = "placeholder"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 2
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = markets
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 5, "kalshi": 0})

            await self._make_runner(session).run_once()

        called_markets = MockRelationService.return_value.run.await_args.args[0]
        assert called_markets == markets[:2]
        MockDivergence.return_value.scan.assert_called_once_with(markets[:2])

    @pytest.mark.anyio
    async def test_run_once_continues_after_compile_failure(self):
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx
        markets = [MagicMock(id="pm:broken"), MagicMock(id="pm:ok")]

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService"),
            patch("parallax.pipeline.runner.TrackerService"),
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = markets
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 2, "kalshi": 0})

            compile_mock = AsyncMock(side_effect=[RuntimeError("boom"), None])
            MockCompiler.return_value.compile = compile_mock

            summary = await self._make_runner(session).run_once()

        assert summary.contracts_compiled == 1
        assert len(summary.errors) == 1
        assert "compile:pm:broken:boom" in summary.errors[0]
        assert compile_mock.await_count == 2

    @pytest.mark.anyio
    async def test_run_once_uses_replay_path_when_history_available(self):
        """When orderbook disabled and replay history exists, evaluate_with_replay is called."""
        from parallax.execution.replay_stats import ReplayStats

        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx

        candidate = MagicMock()
        candidate.id = MagicMock(__str__=lambda s: "cand-replay")
        candidate.opportunity_type = "pure_arbitrage"
        candidate.court_decision = "APPROVED"
        candidate.payoff_matrix = {
            "legs": [], "total_cost": 0.1, "scenarios": [],
            "worst_case_payoff": 0.05, "best_case_payoff": 0.05,
            "breaking_scenario": None, "opportunity_type": "pure_arbitrage",
            "friction_bps": 50,
        }

        stats = ReplayStats(
            opportunity_type="pure_arbitrage",
            n_settled=5,
            win_rate=0.8,
            mean_edge_capture=0.7,
        )

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService") as MockCourt,
            patch("parallax.pipeline.runner.TrackerService") as MockTracker,
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
            patch("parallax.pipeline.runner.ReplayStatisticsService") as MockReplay,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_settings.orderbook_enabled = False
            mock_settings.runtime_global_pause = False
            mock_settings.runtime_degraded_read_only = False
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = []
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = [candidate]
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockCourt.return_value.evaluate_with_replay.return_value = MagicMock(value="WATCHLIST")
            MockCourt.return_value.evaluate.return_value = MagicMock(value="WATCHLIST")
            MockTracker.return_value.open_position.return_value = None
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 0, "kalshi": 0})
            MockReplay.return_value.get_stats.return_value = stats

            await self._make_runner(session).run_once()

        MockCourt.return_value.evaluate_with_replay.assert_called_once()
        MockCourt.return_value.evaluate.assert_not_called()

    @pytest.mark.anyio
    async def test_run_once_uses_heuristic_when_no_replay_history(self):
        """When orderbook disabled and no replay history, evaluate (heuristic) is called."""
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx

        candidate = MagicMock()
        candidate.id = MagicMock(__str__=lambda s: "cand-heuristic")
        candidate.opportunity_type = "pure_arbitrage"
        candidate.court_decision = "APPROVED"
        candidate.payoff_matrix = {
            "legs": [], "total_cost": 0.1, "scenarios": [],
            "worst_case_payoff": 0.05, "best_case_payoff": 0.05,
            "breaking_scenario": None, "opportunity_type": "pure_arbitrage",
            "friction_bps": 50,
        }

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService") as MockCourt,
            patch("parallax.pipeline.runner.TrackerService") as MockTracker,
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
            patch("parallax.pipeline.runner.ReplayStatisticsService") as MockReplay,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_settings.orderbook_enabled = False
            mock_settings.runtime_global_pause = False
            mock_settings.runtime_degraded_read_only = False
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = []
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = [candidate]
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockCourt.return_value.evaluate.return_value = MagicMock(value="WATCHLIST")
            MockCourt.return_value.evaluate_with_replay.return_value = MagicMock(value="WATCHLIST")
            MockTracker.return_value.open_position.return_value = None
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 0, "kalshi": 0})
            MockReplay.return_value.get_stats.return_value = None  # no history

            await self._make_runner(session).run_once()

        MockCourt.return_value.evaluate.assert_called_once()
        MockCourt.return_value.evaluate_with_replay.assert_not_called()

    @pytest.mark.anyio
    async def test_run_once_settles_closed_positions(self):
        """Scanner settles positions and positions_settled counter is incremented."""
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService"),
            patch("parallax.pipeline.runner.TrackerService"),
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
            patch("parallax.pipeline.runner.ReplayStatisticsService"),
            patch("parallax.pipeline.runner.SettlementScannerService") as MockScanner,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_settings.orderbook_enabled = False
            mock_settings.runtime_global_pause = False
            mock_settings.runtime_degraded_read_only = False
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = []
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 0, "kalshi": 0})
            MockScanner.return_value.scan_and_settle.return_value = ["pos-1", "pos-2"]

            summary = await self._make_runner(session).run_once()

        assert summary.positions_settled == 2

    @pytest.mark.anyio
    async def test_run_once_scanner_exception_does_not_abort_run(self):
        """A scanner failure is caught and the run completes normally with zero settled."""
        session = MagicMock()
        session.commit = MagicMock()
        session.begin_nested.side_effect = self._nested_tx

        with (
            patch("parallax.pipeline.runner.settings") as mock_settings,
            patch("parallax.pipeline.runner.build_readiness_payload") as mock_readiness,
            patch("parallax.pipeline.runner.MarketRepository") as MockMarket,
            patch("parallax.pipeline.runner.PostgresGraphRepository"),
            patch("parallax.pipeline.runner.AuditService"),
            patch("parallax.pipeline.runner.IdentityService") as MockIdentity,
            patch("parallax.pipeline.runner.RelationAnalysisService") as MockRelationService,
            patch("parallax.pipeline.runner.DivergenceService") as MockDivergence,
            patch("parallax.pipeline.runner.CandidateRepository") as MockCandidates,
            patch("parallax.pipeline.runner.CourtService"),
            patch("parallax.pipeline.runner.TrackerService"),
            patch("parallax.pipeline.runner.CompilerService") as MockCompiler,
            patch("parallax.pipeline.runner.AnthropicCompilerProvider"),
            patch("parallax.pipeline.runner.SemanticRelationAnalyzer"),
            patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
            patch("parallax.pipeline.runner.ReplayStatisticsService"),
            patch("parallax.pipeline.runner.SettlementScannerService") as MockScanner,
        ):
            mock_settings.anthropic_api_key = "test-key"
            mock_settings.friction_bps = 50
            mock_settings.polymarket_max_events_per_poll = 50
            mock_settings.kalshi_max_events_per_poll = 50
            mock_settings.pipeline_max_open_markets = 0
            mock_settings.orderbook_enabled = False
            mock_settings.runtime_global_pause = False
            mock_settings.runtime_degraded_read_only = False
            mock_readiness.return_value = MagicMock(model_dump=lambda **kwargs: {"checks": {}, "controls": {}})

            MockMarket.return_value.list_open.return_value = []
            MockIdentity.return_value.resolve_all_ungrouped.return_value = 0
            MockRelationService.return_value.run = AsyncMock(return_value=0)
            MockDivergence.return_value.scan.return_value = 0
            MockCandidates.return_value.list_open.return_value = []
            MockCandidates.return_value.get_decision_snapshot.return_value = None
            MockCandidates.return_value.snapshot_to_schema.return_value = None
            MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())
            MockIngestor.return_value.run_once = AsyncMock(return_value={"polymarket": 0, "kalshi": 0})
            MockScanner.return_value.scan_and_settle.side_effect = RuntimeError("scanner boom")

            summary = await self._make_runner(session).run_once()

        assert summary is not None
        assert summary.positions_settled == 0
