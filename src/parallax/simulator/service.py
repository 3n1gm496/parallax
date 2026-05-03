from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.candidates.repository import CandidateRepository
from parallax.execution.estimator import DepthAwareExecutablePriceEstimator
from parallax.execution.fill_simulator import DepthAwareFillSimulator
from parallax.execution.replay_stats import ReplayStatisticsService
from parallax.execution.schemas import OrderbookSnapshot
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.shared.relation_signals import get_relation_signals
from parallax.shared.schemas import OpportunityType, PayoffMatrix, RiskScore, SimulationResult


class SimulatorService:
    """Simulate a candidate trade with a lightweight execution heuristic.

    The model is intentionally simple but no longer assumes perfect execution:
    it degrades the stored post-friction payoff using a slippage estimate derived
    from leg count and candidate risk, and reduces fill probability as structural
    complexity rises.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CandidateRepository(session)
        self._graph_repo = PostgresGraphRepository(session)

    def simulate(self, candidate_id: str) -> SimulationResult:
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
        risk = RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
        relation = self._load_primary_relation(candidate.market_ids)
        relation_signals = get_relation_signals(relation)
        opportunity_type = OpportunityType(candidate.opportunity_type)
        leg_count = len(matrix.legs)
        platforms = [leg.platform or "unknown" for leg in matrix.legs]
        slippage_bps = self._estimate_slippage_bps(leg_count, risk, opportunity_type, relation_signals, platforms)
        slippage_cost = matrix.total_cost * slippage_bps / 10_000
        fill_probability = self._estimate_fill_probability(
            leg_count, risk, opportunity_type, relation_signals, platforms
        )
        spread_cross_cost = self._spread_cross_cost(matrix.total_cost, platforms, opportunity_type)
        stale_quote_cost = self._stale_quote_cost(matrix.total_cost, relation_signals, platforms)
        partial_fill_cost = self._partial_fill_cost(matrix.worst_case_payoff, fill_probability, opportunity_type)
        non_execution_cost = self._non_execution_cost(matrix.total_cost, fill_probability)
        total_execution_drag = (
            slippage_cost + spread_cross_cost + stale_quote_cost + partial_fill_cost + non_execution_cost
        )
        simulated_pnl = matrix.worst_case_payoff - total_execution_drag
        risk_flags = self._risk_flags(opportunity_type, relation_signals, risk, platforms, fill_probability)
        note = (
            f"venue-aware execution model: displayed edge {matrix.worst_case_payoff:.6f}, "
            f"drag {total_execution_drag:.6f} across slippage/spread/stale/partial/non-execution"
        )

        return SimulationResult(
            candidate_id=candidate_id,
            displayed_edge=round(matrix.worst_case_payoff, 6),
            executable_edge=round(simulated_pnl, 6),
            simulated_pnl=round(simulated_pnl, 6),
            friction_bps=matrix.friction_bps,
            fill_probability=fill_probability,
            is_executable=simulated_pnl > 0,
            note=note,
            estimated_slippage_bps=slippage_bps,
            estimated_slippage_cost=round(slippage_cost, 6),
            spread_cross_cost=round(spread_cross_cost, 6),
            stale_quote_cost=round(stale_quote_cost, 6),
            partial_fill_cost=round(partial_fill_cost, 6),
            non_execution_cost=round(non_execution_cost, 6),
            execution_quality=self._execution_quality(fill_probability),
            risk_flags=risk_flags,
            venue_breakdown=self._venue_breakdown(platforms, opportunity_type),
        )

    def simulate_snapshot(
        self,
        candidate_id: str,
        snapshots: dict[str, OrderbookSnapshot | None],
    ) -> SimulationResult:
        """Snapshot-based simulation. Snapshots keyed by market_id.

        Falls back to heuristic per-leg when snapshot is missing,
        and marks execution_model as 'degraded' in that case.
        """
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
        risk = RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
        relation = self._load_primary_relation(candidate.market_ids)
        relation_signals = get_relation_signals(relation)
        opportunity_type = OpportunityType(candidate.opportunity_type)

        estimator = DepthAwareExecutablePriceEstimator()
        fill_sim = DepthAwareFillSimulator()

        total_slippage = 0.0
        worst_fill_probability = 1.0
        worst_partial_fill_risk = 0.0
        snapshot_ids: list[str] = []
        all_supported = True
        any_stale = False
        any_snapshot_missing = False

        for leg in matrix.legs:
            snap = snapshots.get(leg.market_id)
            if snap is None:
                any_snapshot_missing = True
                # Fallback: heuristic slippage for this leg
                leg_slippage = leg.cost * 0.005 if leg.cost else 0.0
                total_slippage += leg_slippage
                continue

            snapshot_ids.append(snap.id)
            if snap.is_stale:
                any_stale = True

            qty = leg.quantity
            ep = estimator.estimate(snap, "buy", qty)
            fs = fill_sim.simulate(snap, "buy", qty)

            if ep.vwap_price is not None and ep.vwap_price > leg.price:
                total_slippage += (ep.vwap_price - leg.price) * qty

            if not ep.is_supported:
                all_supported = False

            worst_fill_probability = min(worst_fill_probability, fs.fill_probability)
            worst_partial_fill_risk = max(worst_partial_fill_risk, fs.partial_fill_risk)

        execution_model: str
        if any_snapshot_missing:
            execution_model = "degraded"
        else:
            execution_model = "snapshot_based"

        simulated_pnl = matrix.worst_case_payoff - total_slippage
        quote_staleness: float | None = None
        if snapshot_ids:
            staleness_values = [
                snapshots[leg.market_id].staleness_seconds
                for leg in matrix.legs
                if leg.market_id in snapshots and snapshots[leg.market_id] is not None
            ]
            quote_staleness = max(staleness_values) if staleness_values else None

        note = (
            f"snapshot execution model ({execution_model}): "
            f"displayed_edge={matrix.worst_case_payoff:.6f}, "
            f"slippage_drag={total_slippage:.6f}, "
            f"depth_supported={all_supported}, "
            f"any_stale={any_stale}"
        )

        risk_flags = self._risk_flags(
            opportunity_type, relation_signals, risk,
            [leg.platform or "unknown" for leg in matrix.legs],
            worst_fill_probability,
        )
        if any_stale:
            risk_flags.append("stale_quote")
        if not all_supported:
            risk_flags.append("insufficient_depth")
        if worst_partial_fill_risk > 0.5:
            risk_flags.append("high_partial_fill_risk")

        return SimulationResult(
            candidate_id=candidate_id,
            displayed_edge=round(matrix.worst_case_payoff, 6),
            executable_edge=round(simulated_pnl, 6),
            simulated_pnl=round(simulated_pnl, 6),
            friction_bps=matrix.friction_bps,
            fill_probability=round(worst_fill_probability, 4),
            is_executable=simulated_pnl > 0 and all_supported and not any_stale,
            note=note,
            estimated_slippage_bps=int(round(total_slippage / matrix.total_cost * 10000)) if matrix.total_cost > 0 else 0,
            estimated_slippage_cost=round(total_slippage, 6),
            spread_cross_cost=0.0,
            stale_quote_cost=0.0,
            partial_fill_cost=0.0,
            non_execution_cost=0.0,
            execution_quality=self._execution_quality(worst_fill_probability),
            risk_flags=risk_flags,
            venue_breakdown=self._venue_breakdown(
                [leg.platform or "unknown" for leg in matrix.legs], opportunity_type
            ),
            execution_model=execution_model,  # type: ignore[arg-type]
            quote_staleness_seconds=quote_staleness,
            snapshot_ids=snapshot_ids,
            depth_support=all_supported,
            partial_fill_risk=round(worst_partial_fill_risk, 4),
        )

    def simulate_replay(self, candidate_id: str) -> SimulationResult:
        """Replay-calibrated simulation using settled position history for this opportunity type.

        Falls back to heuristic execution_model when history is insufficient.
        """
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        heuristic = self.simulate(candidate_id)

        stats = ReplayStatisticsService(self._session).get_stats(candidate.opportunity_type)
        if stats is None:
            return heuristic

        effective_capture = min(max(stats.mean_edge_capture, 0.0), 1.5)
        adjusted_pnl = round(heuristic.simulated_pnl * effective_capture, 6)
        adjusted_fill = round(min(1.0, max(0.2, stats.win_rate)), 4)

        note = (
            f"replay-calibrated execution model: n_settled={stats.n_settled}, "
            f"win_rate={stats.win_rate:.3f}, mean_edge_capture={stats.mean_edge_capture:.3f}, "
            f"adjusted_pnl={adjusted_pnl:.6f}"
        )

        return SimulationResult(
            candidate_id=candidate_id,
            displayed_edge=heuristic.displayed_edge,
            executable_edge=adjusted_pnl,
            simulated_pnl=adjusted_pnl,
            friction_bps=heuristic.friction_bps,
            fill_probability=adjusted_fill,
            is_executable=adjusted_pnl > 0,
            note=note,
            estimated_slippage_bps=heuristic.estimated_slippage_bps,
            estimated_slippage_cost=heuristic.estimated_slippage_cost,
            spread_cross_cost=heuristic.spread_cross_cost,
            stale_quote_cost=heuristic.stale_quote_cost,
            partial_fill_cost=heuristic.partial_fill_cost,
            non_execution_cost=heuristic.non_execution_cost,
            execution_quality=self._execution_quality(adjusted_fill),
            risk_flags=heuristic.risk_flags,
            venue_breakdown=heuristic.venue_breakdown,
            execution_model="replay_based",
            model_version="replay-v1",
        )

    @staticmethod
    def _estimate_slippage_bps(
        leg_count: int,
        risk: RiskScore | None,
        opportunity_type: OpportunityType,
        relation_signals: dict,
        platforms: list[str],
    ) -> int:
        base_bps = 5
        leg_bps = max(0, leg_count - 1) * 4
        risk_bps = int(round((risk.composite if risk is not None else 0.25) * 20))
        type_bps = 6 if opportunity_type in {
            OpportunityType.DUPLICATE_DIVERGENCE,
            OpportunityType.SEMANTIC_ARBITRAGE,
            OpportunityType.SUBSET_VIOLATION,
        } else 0
        cross_platform_bps = 5 if len(set(platforms)) > 1 else 0
        oracle_bps = 12 if relation_signals["oracle_mismatch"] else 0
        deadline_bps = 8 if relation_signals["deadline_mismatch"] else 0
        ambiguity_bps = 10 if relation_signals["ambiguity_level"] == "high" else 4 if relation_signals["ambiguity_level"] == "medium" else 0
        return base_bps + leg_bps + risk_bps + type_bps + cross_platform_bps + oracle_bps + deadline_bps + ambiguity_bps

    @staticmethod
    def _estimate_fill_probability(
        leg_count: int,
        risk: RiskScore | None,
        opportunity_type: OpportunityType,
        relation_signals: dict,
        platforms: list[str],
    ) -> float:
        probability = 0.98 - max(0, leg_count - 1) * 0.08
        probability -= (risk.composite if risk is not None else 0.25) * 0.35
        if len(set(platforms)) > 1:
            probability -= 0.06
        if opportunity_type in {
            OpportunityType.DUPLICATE_DIVERGENCE,
            OpportunityType.SEMANTIC_ARBITRAGE,
            OpportunityType.SUBSET_VIOLATION,
        }:
            probability -= 0.08
        if relation_signals["oracle_mismatch"]:
            probability -= 0.18
        if relation_signals["deadline_mismatch"]:
            probability -= 0.1
        if relation_signals["ambiguity_level"] == "high":
            probability -= 0.14
        elif relation_signals["ambiguity_level"] == "medium":
            probability -= 0.06
        return round(min(1.0, max(0.2, probability)), 4)

    @staticmethod
    def _execution_quality(fill_probability: float) -> str:
        if fill_probability >= 0.8:
            return "high"
        if fill_probability >= 0.55:
            return "medium"
        return "low"

    @staticmethod
    def _spread_cross_cost(total_cost: float, platforms: list[str], opportunity_type: OpportunityType) -> float:
        base = 0.0025 if len(set(platforms)) > 1 else 0.001
        if opportunity_type in {
            OpportunityType.DUPLICATE_DIVERGENCE,
            OpportunityType.SEMANTIC_ARBITRAGE,
            OpportunityType.SUBSET_VIOLATION,
        }:
            base += 0.001
        return total_cost * base

    @staticmethod
    def _stale_quote_cost(total_cost: float, relation_signals: dict, platforms: list[str]) -> float:
        base = 0.0
        if len(set(platforms)) > 1:
            base += 0.0015
        if relation_signals["deadline_mismatch"]:
            base += 0.001
        if relation_signals["oracle_mismatch"]:
            base += 0.001
        return total_cost * base

    @staticmethod
    def _partial_fill_cost(displayed_edge: float, fill_probability: float, opportunity_type: OpportunityType) -> float:
        exposure = max(0.0, 1.0 - fill_probability)
        multiplier = 0.2
        if opportunity_type in {
            OpportunityType.DUPLICATE_DIVERGENCE,
            OpportunityType.SEMANTIC_ARBITRAGE,
            OpportunityType.SUBSET_VIOLATION,
        }:
            multiplier = 0.3
        return max(0.0, displayed_edge) * exposure * multiplier

    @staticmethod
    def _non_execution_cost(total_cost: float, fill_probability: float) -> float:
        return total_cost * max(0.0, 1.0 - fill_probability) * 0.01

    @staticmethod
    def _risk_flags(
        opportunity_type: OpportunityType,
        relation_signals: dict,
        risk: RiskScore | None,
        platforms: list[str],
        fill_probability: float,
    ) -> list[str]:
        flags: list[str] = []
        if opportunity_type in {
            OpportunityType.DUPLICATE_DIVERGENCE,
            OpportunityType.SEMANTIC_ARBITRAGE,
            OpportunityType.SUBSET_VIOLATION,
        }:
            flags.append("semantic_execution")
        if len(set(platforms)) > 1:
            flags.append("cross_venue_execution")
        if relation_signals["oracle_mismatch"]:
            flags.append("oracle_mismatch")
        if relation_signals["deadline_mismatch"]:
            flags.append("deadline_mismatch")
        if relation_signals["ambiguity_level"] == "high":
            flags.append("high_ambiguity")
        elif relation_signals["ambiguity_level"] == "medium":
            flags.append("medium_ambiguity")
        if risk is not None and risk.composite >= 0.5:
            flags.append("high_composite_risk")
        if fill_probability < 0.55:
            flags.append("non_execution_risk")
        return flags

    @staticmethod
    def _venue_breakdown(platforms: list[str], opportunity_type: OpportunityType) -> dict[str, object]:
        return {
            "platforms": platforms,
            "cross_platform": len(set(platforms)) > 1,
            "opportunity_type": opportunity_type.value,
            "assumptions": {
                "polymarket": "midpoint-to-executable spread crossing heuristic",
                "kalshi": "yes-no reciprocity and quote asymmetry heuristic",
            },
        }

    def _load_primary_relation(self, market_ids: list[str]) -> dict | None:
        if len(market_ids) < 2:
            return None
        anchor = market_ids[0]
        counterpart_ids = set(market_ids[1:])
        relations = self._graph_repo.get_relations(anchor)
        return next(
            (
                relation
                for relation in relations
                if {relation["from_market_id"], relation["to_market_id"]} == {anchor, *counterpart_ids}
            ),
            None,
        )
