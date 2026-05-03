from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.candidates.evidence import load_relation_evidence
from parallax.candidates.repository import CandidateRepository
from parallax.config import settings
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.ingestion.market_repository import MarketRepository
from parallax.shared.relation_signals import get_relation_signals
from parallax.shared.schemas import (
    CourtAssessment,
    CourtDecision,
    DecisionGate,
    IdentityResolutionStatus,
    OpportunityType,
    RelationType,
    RiskScore,
    SimulationResult,
)
from parallax.execution.schemas import OrderbookSnapshot
from parallax.simulator.service import SimulatorService

_SEMANTIC_OPPORTUNITY_TYPES = {
    OpportunityType.DUPLICATE_DIVERGENCE,
    OpportunityType.SEMANTIC_ARBITRAGE,
    OpportunityType.SUBSET_VIOLATION,
}

_STRICT_OPPORTUNITY_TYPES = {
    OpportunityType.DUPLICATE_DIVERGENCE,
    OpportunityType.SEMANTIC_ARBITRAGE,
}


class CourtService:
    """Evaluate candidates and assign a pragmatic court decision.

    This is still a lightweight court, but it now uses the stored risk score
    rather than only the raw payoff sign.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CandidateRepository(session)
        self._market_repo = MarketRepository(session)
        self._graph_repo = PostgresGraphRepository(session)
        self._simulator = SimulatorService(session)

    def assess(self, candidate_id: str) -> CourtAssessment:
        assessment, _ = self.assess_with_simulation(candidate_id)
        return assessment

    def assess_with_simulation(self, candidate_id: str) -> tuple[CourtAssessment, SimulationResult]:
        simulation = self._simulator.simulate(candidate_id)
        return self._run_assessment(candidate_id, simulation)

    def assess_with_snapshots(
        self,
        candidate_id: str,
        snapshots: dict[str, OrderbookSnapshot | None],
    ) -> tuple[CourtAssessment, SimulationResult, RiskScore | None]:
        """Run assessment using snapshot-based simulation, with extra orderbook gates."""
        simulation = self._simulator.simulate_snapshot(candidate_id, snapshots)
        adjusted_risk = self._compute_adjusted_risk(candidate_id, simulation)
        base_assessment, _ = self._run_assessment(candidate_id, simulation, risk_override=adjusted_risk)

        # Inject orderbook-specific gates
        extra_gates, extra_reasons, downgrade = self._orderbook_gates(simulation)
        gates = list(base_assessment.gates) + extra_gates
        reasons = list(base_assessment.reasons) + extra_reasons
        decision = base_assessment.decision
        if downgrade and decision == CourtDecision.APPROVED:
            decision = CourtDecision.WATCHLIST

        assessment = CourtAssessment(
            decision=decision,
            simulated_pnl=base_assessment.simulated_pnl,
            fill_probability=base_assessment.fill_probability,
            composite_risk=base_assessment.composite_risk,
            reasons=reasons,
            opportunity_type=base_assessment.opportunity_type,
            relation_type=base_assessment.relation_type,
            risk_flags=list(simulation.risk_flags),
            gates=gates,
            policy_version="court-v2-snapshot",
        )
        return assessment, simulation, adjusted_risk

    def _compute_adjusted_risk(
        self, candidate_id: str, simulation: SimulationResult
    ) -> RiskScore | None:
        candidate = self._repo.get(candidate_id)
        if candidate is None or not candidate.risk_scores:
            return None
        base = RiskScore.model_validate(candidate.risk_scores)
        return RiskScore.adjust_from_simulation(base, simulation)

    @staticmethod
    def _orderbook_gates(
        simulation: SimulationResult,
    ) -> tuple[list[DecisionGate], list[str], bool]:
        """Return extra gates, reasons, and whether to downgrade APPROVED → WATCHLIST."""
        gates: list[DecisionGate] = []
        reasons: list[str] = []
        downgrade = False

        staleness = simulation.quote_staleness_seconds
        if staleness is not None:
            threshold = settings.court_max_quote_staleness_seconds
            if staleness > threshold:
                gates.append(
                    DecisionGate(
                        name="quote_staleness",
                        status="watchlist",
                        observed=f"{staleness:.1f}s",
                        threshold=f"<= {threshold:.0f}s",
                        detail="snapshot is stale; executable price may not reflect current market",
                    )
                )
                reasons.append(f"quote staleness {staleness:.1f}s exceeds threshold {threshold:.0f}s")
                downgrade = True
            else:
                gates.append(
                    DecisionGate(
                        name="quote_staleness",
                        status="pass",
                        observed=f"{staleness:.1f}s",
                        threshold=f"<= {threshold:.0f}s",
                    )
                )

        if simulation.depth_support is not None:
            if not simulation.depth_support:
                gates.append(
                    DecisionGate(
                        name="depth_support",
                        status="watchlist",
                        observed="insufficient",
                        threshold="full_fill_supported",
                        detail="book depth does not support the required trade size",
                    )
                )
                reasons.append("orderbook depth insufficient to support full fill")
                downgrade = True
            else:
                gates.append(
                    DecisionGate(
                        name="depth_support",
                        status="pass",
                        observed="supported",
                        threshold="full_fill_supported",
                    )
                )

        partial_risk = simulation.partial_fill_risk
        threshold_pf = settings.court_partial_fill_inversion_threshold
        if partial_risk > threshold_pf:
            gates.append(
                DecisionGate(
                    name="partial_fill_inversion",
                    status="watchlist",
                    observed=f"{partial_risk:.3f}",
                    threshold=f"<= {threshold_pf:.3f}",
                    detail="partial fill risk may invert payoff on incomplete execution",
                )
            )
            reasons.append(f"partial fill inversion risk {partial_risk:.3f} exceeds threshold")
            downgrade = True
        else:
            gates.append(
                DecisionGate(
                    name="partial_fill_inversion",
                    status="pass",
                    observed=f"{partial_risk:.3f}",
                    threshold=f"<= {threshold_pf:.3f}",
                )
            )

        return gates, reasons, downgrade

    def _run_assessment(
        self,
        candidate_id: str,
        simulation: SimulationResult,
        risk_override: RiskScore | None = None,
    ) -> tuple[CourtAssessment, SimulationResult]:
        """Internal: run the assessment logic given a pre-computed simulation."""
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        risk = risk_override if risk_override is not None else (
            RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
        )
        opportunity_type = OpportunityType(candidate.opportunity_type)
        markets = [
            market
            for market in (self._market_repo.get(market_id) for market_id in candidate.market_ids)
            if market is not None
        ]
        relation = load_relation_evidence(self._session, candidate.market_ids)
        if relation is None:
            relation = self._load_primary_relation(candidate.market_ids)
        relation_type = self._relation_type(relation)
        relation_confidence = self._relation_confidence(relation)
        relation_tradeable = self._relation_tradeable(relation)
        relation_proof_status = self._relation_proof_status(relation)
        breaking_scenarios = self._breaking_scenarios(relation)
        abstention_reason = self._abstention_reason(relation)
        relation_is_confirmed = self._relation_is_confirmed(relation)
        relation_signals = get_relation_signals(relation)
        identity_status = self._identity_status(relation)
        identity_blocking_reason = self._identity_blocking_reason(relation)
        oracle_mismatch = self._has_oracle_mismatch(markets, relation_type) or relation_signals["oracle_mismatch"]
        deadline_mismatch = relation_signals["deadline_mismatch"]
        ambiguity_level = relation_signals["ambiguity_level"]
        shared_ambiguity_terms = relation_signals["shared_ambiguity_terms"]

        reasons: list[str] = []
        gates: list[DecisionGate] = []
        risk_flags = list(simulation.risk_flags)

        if candidate.worst_case_payoff <= 0:
            reasons.append("stored worst-case payoff is non-positive")
            gates.append(
                DecisionGate(
                    name="stored_payoff",
                    status="reject",
                    observed=f"{candidate.worst_case_payoff:.6f}",
                    threshold="> 0",
                    detail="stored payoff fails before execution simulation",
                )
            )
            decision = CourtDecision.REJECTED
        elif simulation.simulated_pnl <= 0:
            reasons.append("simulated execution drag removes the edge")
            gates.append(
                DecisionGate(
                    name="simulated_pnl",
                    status="reject",
                    observed=f"{simulation.simulated_pnl:.6f}",
                    threshold="> 0",
                    detail="execution drag fully removes expected edge",
                )
            )
            decision = CourtDecision.REJECTED
        elif (
            opportunity_type in _SEMANTIC_OPPORTUNITY_TYPES
            and abstention_reason
            and relation is not None
            and not relation_is_confirmed
        ):
            reasons.append(abstention_reason)
            gates.append(
                DecisionGate(
                    name="relation_confirmation",
                    status="watchlist",
                    observed="unconfirmed",
                    threshold="confirmed",
                    detail=abstention_reason,
                )
            )
            decision = CourtDecision.ABSTAINED
        elif opportunity_type in _SEMANTIC_OPPORTUNITY_TYPES and breaking_scenarios:
            reasons.append("semantic analysis found breaking scenarios for this relation")
            gates.append(
                DecisionGate(
                    name="breaking_scenarios",
                    status="reject",
                    observed=str(len(breaking_scenarios)),
                    threshold="0",
                    detail="semantic relation contains explicit edge-breaking counterexamples",
                )
            )
            decision = CourtDecision.REJECTED
        elif opportunity_type in _STRICT_OPPORTUNITY_TYPES and identity_status != IdentityResolutionStatus.VERIFIED:
            reasons.append(identity_blocking_reason or "identity layer did not verify the semantic match")
            gates.append(
                DecisionGate(
                    name="identity_verification",
                    status="reject" if identity_status == IdentityResolutionStatus.REJECTED else "watchlist",
                    observed=identity_status.value,
                    threshold=IdentityResolutionStatus.VERIFIED.value,
                    detail=identity_blocking_reason,
                )
            )
            decision = (
                CourtDecision.REJECTED
                if identity_status == IdentityResolutionStatus.REJECTED
                else CourtDecision.ABSTAINED
            )
        elif opportunity_type in _STRICT_OPPORTUNITY_TYPES and oracle_mismatch:
            reasons.append("oracle mismatch makes the semantic spread non-fungible")
            gates.append(
                DecisionGate(
                    name="oracle_consistency",
                    status="reject",
                    observed="mismatch",
                    threshold="match",
                )
            )
            decision = CourtDecision.REJECTED
        elif opportunity_type in _STRICT_OPPORTUNITY_TYPES and deadline_mismatch:
            reasons.append("deadline drift makes the semantic spread non-fungible")
            gates.append(
                DecisionGate(
                    name="deadline_consistency",
                    status="reject",
                    observed="mismatch",
                    threshold="match",
                )
            )
            decision = CourtDecision.REJECTED
        elif relation_type is not None and not relation_tradeable:
            reasons.append("relation layer did not mark this edge as tradeable")
            gates.append(
                DecisionGate(
                    name="relation_tradeability",
                    status="reject",
                    observed="false",
                    threshold="true",
                    detail=relation_proof_status,
                )
            )
            decision = CourtDecision.REJECTED
        else:
            decision = CourtDecision.APPROVED
            reasons.append("positive stored payoff survives execution drag")
            gates.append(
                DecisionGate(
                    name="stored_payoff",
                    status="pass",
                    observed=f"{candidate.worst_case_payoff:.6f}",
                    threshold="> 0",
                )
            )
            gates.append(
                DecisionGate(
                    name="simulated_pnl",
                    status="pass",
                    observed=f"{simulation.simulated_pnl:.6f}",
                    threshold=f">= {self._min_simulated_pnl(opportunity_type):.6f}",
                    detail=f"execution quality: {simulation.execution_quality}",
                )
            )
            if relation_type is not None:
                reasons.append(f"relation context: {relation_type.value}")
            if ambiguity_level != "low":
                reasons.append(f"semantic ambiguity level: {ambiguity_level}")
            if shared_ambiguity_terms:
                reasons.append(f"shared ambiguity terms: {', '.join(shared_ambiguity_terms)}")
            if relation_confidence is not None and relation_confidence < settings.semantic_min_relation_confidence:
                reasons.append("relation confidence is below the semantic approval floor")
                gates.append(
                    DecisionGate(
                        name="relation_confidence",
                        status="watchlist",
                        observed=f"{relation_confidence:.4f}",
                        threshold=f">= {settings.semantic_min_relation_confidence:.4f}",
                    )
                )
                decision = CourtDecision.WATCHLIST
            elif relation_confidence is not None:
                gates.append(
                    DecisionGate(
                        name="relation_confidence",
                        status="pass",
                        observed=f"{relation_confidence:.4f}",
                        threshold=f">= {settings.semantic_min_relation_confidence:.4f}",
                    )
                )
            if relation_type == RelationType.NOT_RELATED:
                reasons.append("relation evidence persisted a negative semantic outcome")
                gates.append(
                    DecisionGate(
                        name="relation_outcome",
                        status="watchlist",
                        observed="not_related",
                        threshold="actionable semantic relation",
                    )
                )
                decision = CourtDecision.WATCHLIST
            max_risk = self._max_composite_risk(opportunity_type)
            min_fill_probability = self._min_fill_probability(opportunity_type)
            min_simulated_pnl = self._min_simulated_pnl(opportunity_type)
            if risk is not None and risk.composite > max_risk:
                reasons.append("composite risk exceeds approval threshold for this opportunity type")
                gates.append(
                    DecisionGate(
                        name="composite_risk",
                        status="watchlist",
                        observed=f"{risk.composite:.4f}",
                        threshold=f"<= {max_risk:.4f}",
                    )
                )
                decision = CourtDecision.WATCHLIST
            elif risk is not None:
                gates.append(
                    DecisionGate(
                        name="composite_risk",
                        status="pass",
                        observed=f"{risk.composite:.4f}",
                        threshold=f"<= {max_risk:.4f}",
                    )
                )
            if simulation.fill_probability < min_fill_probability:
                reasons.append("estimated fill probability is too low for this opportunity type")
                gates.append(
                    DecisionGate(
                        name="fill_probability",
                        status="watchlist",
                        observed=f"{simulation.fill_probability:.4f}",
                        threshold=f">= {min_fill_probability:.4f}",
                    )
                )
                decision = CourtDecision.WATCHLIST
            else:
                gates.append(
                    DecisionGate(
                        name="fill_probability",
                        status="pass",
                        observed=f"{simulation.fill_probability:.4f}",
                        threshold=f">= {min_fill_probability:.4f}",
                    )
                )
            if simulation.simulated_pnl < min_simulated_pnl:
                reasons.append("simulated pnl is below the minimum approval threshold for this opportunity type")
                gates.append(
                    DecisionGate(
                        name="simulated_edge_floor",
                        status="watchlist",
                        observed=f"{simulation.simulated_pnl:.6f}",
                        threshold=f">= {min_simulated_pnl:.6f}",
                    )
                )
                decision = CourtDecision.WATCHLIST
            else:
                gates.append(
                    DecisionGate(
                        name="simulated_edge_floor",
                        status="pass",
                        observed=f"{simulation.simulated_pnl:.6f}",
                        threshold=f">= {min_simulated_pnl:.6f}",
                    )
                )
            if oracle_mismatch:
                reasons.append("oracle mismatch requires manual settlement review")
                gates.append(
                    DecisionGate(
                        name="oracle_consistency",
                        status="watchlist",
                        observed="mismatch",
                        threshold="match",
                    )
                )
                decision = CourtDecision.WATCHLIST
            if deadline_mismatch:
                reasons.append("deadline mismatch requires manual settlement review")
                gates.append(
                    DecisionGate(
                        name="deadline_consistency",
                        status="watchlist",
                        observed="mismatch",
                        threshold="match",
                    )
                )
                decision = CourtDecision.WATCHLIST
            if ambiguity_level == "high":
                reasons.append("high semantic ambiguity requires manual review")
                gates.append(
                    DecisionGate(
                        name="semantic_ambiguity",
                        status="watchlist",
                        observed="high",
                        threshold="low/medium",
                    )
                )
                decision = CourtDecision.WATCHLIST
            if breaking_scenarios:
                reasons.append("semantic analysis supplied edge-breaking scenarios that require manual review")
                gates.append(
                    DecisionGate(
                        name="breaking_scenarios",
                        status="watchlist",
                        observed=str(len(breaking_scenarios)),
                        threshold="0",
                    )
                )
                decision = CourtDecision.WATCHLIST

        assessment = CourtAssessment(
            decision=decision,
            simulated_pnl=simulation.simulated_pnl,
            fill_probability=simulation.fill_probability,
            composite_risk=risk.composite if risk is not None else None,
            reasons=reasons,
            opportunity_type=opportunity_type,
            relation_type=relation_type,
            risk_flags=risk_flags,
            gates=gates,
            policy_version="court-v2",
        )
        return assessment, simulation

    def evaluate_with_snapshots(
        self,
        candidate_id: str,
        snapshots: dict[str, OrderbookSnapshot | None],
        run_id: str | None = None,
    ) -> CourtDecision:
        """Evaluate using snapshot-based simulation; persist decision and snapshot."""
        assessment, simulation, adjusted_risk = self.assess_with_snapshots(candidate_id, snapshots)
        return self._persist_evaluation(candidate_id, assessment, simulation, run_id, adjusted_risk=adjusted_risk)

    def evaluate_with_replay(self, candidate_id: str, run_id: str | None = None) -> CourtDecision:
        """Evaluate using replay-calibrated simulation; persist decision and snapshot."""
        simulation = self._simulator.simulate_replay(candidate_id)
        assessment, simulation = self._run_assessment(candidate_id, simulation)
        return self._persist_evaluation(candidate_id, assessment, simulation, run_id)

    def evaluate(self, candidate_id: str, run_id: str | None = None) -> CourtDecision:
        assessment, simulation = self.assess_with_simulation(candidate_id)
        return self._persist_evaluation(candidate_id, assessment, simulation, run_id)

    def _persist_evaluation(
        self,
        candidate_id: str,
        assessment: CourtAssessment,
        simulation: SimulationResult,
        run_id: str | None,
        *,
        adjusted_risk: RiskScore | None = None,
    ) -> CourtDecision:
        decision = assessment.decision
        self._repo.update_decision(candidate_id, decision)
        candidate = self._repo.get(candidate_id)
        risk = adjusted_risk
        if risk is None and candidate is not None and candidate.risk_scores:
            risk = RiskScore.model_validate(candidate.risk_scores)
        relation_evidence = load_relation_evidence(self._session, candidate.market_ids) if candidate is not None else None
        self._repo.upsert_decision_snapshot(
            candidate_id,
            run_id=run_id,
            risk_score=risk,
            relation_evidence=relation_evidence,
            simulation_result=simulation,
            court_assessment=assessment,
            evaluated_at=datetime.now(timezone.utc),
        )
        return decision

    @staticmethod
    def _relation_is_confirmed(relation) -> bool:
        if relation is None:
            return False
        if hasattr(relation, "is_confirmed"):
            return bool(relation.is_confirmed)
        evidence = relation.get("evidence", {})
        return bool(evidence.get("is_confirmed", True))

    @staticmethod
    def _relation_tradeable(relation) -> bool:
        if relation is None:
            return False
        if hasattr(relation, "tradeable_relation"):
            return bool(relation.tradeable_relation)
        return bool(relation.get("tradeable_relation", relation.get("evidence", {}).get("tradeable_relation", False)))

    @staticmethod
    def _relation_proof_status(relation) -> str:
        if relation is None:
            return "missing"
        if hasattr(relation, "proof_status"):
            return str(relation.proof_status)
        return str(relation.get("proof_status", relation.get("evidence", {}).get("proof_status", "verified")))

    @staticmethod
    def _abstention_reason(relation) -> str | None:
        if relation is None:
            return "no persisted relation evidence available"
        if hasattr(relation, "abstention_reason"):
            return str(relation.abstention_reason) if relation.abstention_reason else None
        evidence = relation.get("evidence", {})
        reason = evidence.get("abstention_reason")
        return str(reason) if reason else None

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
                if {
                    relation["from_market_id"],
                    relation["to_market_id"],
                }
                == {anchor, *counterpart_ids}
            ),
            None,
        )

    @staticmethod
    def _relation_type(relation) -> RelationType | None:
        if relation is None:
            return None
        if hasattr(relation, "relation_type"):
            return RelationType(relation.relation_type)
        relation_value = relation.get("relation_type")
        return RelationType(relation_value) if relation_value else None

    @staticmethod
    def _relation_confidence(relation) -> float | None:
        if relation is None:
            return None
        if hasattr(relation, "semantic_confidence"):
            confidence = relation.semantic_confidence if relation.semantic_confidence is not None else relation.confidence
            return float(confidence) if isinstance(confidence, (int, float)) else None
        confidence = relation.get("evidence", {}).get("semantic_confidence", relation.get("confidence"))
        return float(confidence) if isinstance(confidence, (int, float)) else None

    @staticmethod
    def _breaking_scenarios(relation) -> list[dict]:
        if relation is None:
            return []
        if hasattr(relation, "breaking_scenarios"):
            scenarios = relation.breaking_scenarios or []
            return [item.model_dump() if hasattr(item, "model_dump") else item for item in scenarios]
        scenarios = relation.get("evidence", {}).get("breaking_scenarios", [])
        return scenarios if isinstance(scenarios, list) else []

    @staticmethod
    def _identity_status(relation) -> IdentityResolutionStatus:
        if relation is None:
            return IdentityResolutionStatus.UNRESOLVED
        if hasattr(relation, "identity_status"):
            return IdentityResolutionStatus(str(relation.identity_status))
        return IdentityResolutionStatus(str(relation.get("identity_status", "unresolved")))

    @staticmethod
    def _identity_blocking_reason(relation) -> str | None:
        if relation is None:
            return "missing identity evidence"
        if hasattr(relation, "identity_blocking_reason"):
            return str(relation.identity_blocking_reason) if relation.identity_blocking_reason else None
        value = relation.get("identity_blocking_reason")
        return str(value) if value else None

    @staticmethod
    def _has_oracle_mismatch(markets: list, relation_type: RelationType | None) -> bool:
        if relation_type == RelationType.SAME_EVENT_DIFFERENT_ORACLE:
            return True
        sources = {
            market.resolution_source.strip().lower()
            for market in markets
            if isinstance(market.resolution_source, str) and market.resolution_source.strip()
        }
        return len(sources) > 1

    @staticmethod
    def _max_composite_risk(opportunity_type: OpportunityType) -> float:
        if opportunity_type in _STRICT_OPPORTUNITY_TYPES:
            return min(settings.court_max_composite_risk, 0.3)
        if opportunity_type == OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING:
            return min(0.55, settings.court_max_composite_risk + 0.1)
        return settings.court_max_composite_risk

    @staticmethod
    def _min_fill_probability(opportunity_type: OpportunityType) -> float:
        if opportunity_type in _STRICT_OPPORTUNITY_TYPES:
            return max(settings.court_min_fill_probability, 0.7)
        if opportunity_type == OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING:
            return max(0.45, settings.court_min_fill_probability - 0.05)
        return settings.court_min_fill_probability

    @staticmethod
    def _min_simulated_pnl(opportunity_type: OpportunityType) -> float:
        if opportunity_type in _STRICT_OPPORTUNITY_TYPES:
            return max(settings.court_min_simulated_pnl, 0.02)
        if opportunity_type == OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING:
            return max(0.005, settings.court_min_simulated_pnl - 0.0025)
        return settings.court_min_simulated_pnl
