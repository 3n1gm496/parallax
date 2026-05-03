from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.candidates.evidence import load_relation_evidence
from parallax.candidates.repository import CandidateRepository
from parallax.db.models import RawMarket
from parallax.graph.repository import GraphRepository
from parallax.shared.relation_signals import get_relation_signals
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    Leg,
    OpportunityType,
    PayoffMatrix,
    RiskScore,
    RelationType,
    Scenario,
)

_MIN_PROFIT_AFTER_FRICTION = 0.005  # 0.5% minimum edge


class DivergenceService:
    """Detect pricing divergences and emit OpportunityCandidate records."""

    def __init__(
        self,
        session: Session,
        graph_repo: GraphRepository,
        friction_bps: int = 50,
    ) -> None:
        self._session = session
        self._graph_repo = graph_repo
        self._candidate_repo = CandidateRepository(session)
        self._friction_bps = friction_bps

    def scan(self, markets: list[RawMarket]) -> int:
        """Check all relations for profitable divergences. Returns count of new candidates."""
        market_map = {m.id: m for m in markets}
        found = 0
        seen_pairs: set[frozenset[str]] = set()

        for m in markets:
            relations = self._graph_repo.get_relations(m.id)
            for rel in relations:
                pair = frozenset([rel["from_market_id"], rel["to_market_id"]])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                relation_evidence = load_relation_evidence(self._session, list(pair))
                if relation_evidence is None:
                    continue
                if relation_evidence.identity_status != IdentityResolutionStatus.VERIFIED:
                    continue
                if not relation_evidence.tradeable_relation:
                    continue
                if str(relation_evidence.proof_status) != "verified":
                    continue

                rtype = RelationType(rel["relation_type"])
                a_id, b_id = rel["from_market_id"], rel["to_market_id"]
                if a_id not in market_map or b_id not in market_map:
                    continue

                a, b = market_map[a_id], market_map[b_id]
                matrix = None

                if rtype == RelationType.MUTUALLY_EXCLUSIVE:
                    matrix = self._check_mutually_exclusive(a, b)
                elif rtype in (RelationType.EQUIVALENT, RelationType.DUPLICATE):
                    matrix = self._check_equivalent(a, b)

                if matrix and matrix.worst_case_payoff > _MIN_PROFIT_AFTER_FRICTION:
                    if self._candidate_repo.candidate_exists([a_id, b_id], matrix.opportunity_type):
                        continue
                    risk_score = self._score_candidate(a, b, relation_evidence)
                    self._candidate_repo.create(
                        market_ids=[a_id, b_id],
                        payoff_matrix=matrix,
                        opportunity_type=matrix.opportunity_type,
                        risk_scores=risk_score.model_dump(),
                    )
                    found += 1

        return found

    def _friction_cost(self, total_cost: float) -> float:
        return total_cost * self._friction_bps / 10_000

    def _check_mutually_exclusive(
        self, a: RawMarket, b: RawMarket
    ) -> PayoffMatrix | None:
        """Buy NO on both legs (equivalent to selling YES). Profit if YES prices sum > 1.0 + friction.

        total_cost = sum of NO-leg prices = (1-p_a) + (1-p_b): capital deployed,
        consistent with EQUIVALENT where total_cost = buy_price + (1-sell_price).
        gross = p_a + p_b - 1.0 (collateral payout minus premium received).
        worst_case_payoff is post-friction; SimulatorService must NOT re-apply.
        """
        if not a.outcome_prices or not b.outcome_prices:
            return None
        p_a = a.outcome_prices[0]
        p_b = b.outcome_prices[0]
        if not isinstance(p_a, (int, float)) or not isinstance(p_b, (int, float)):
            return None
        total_cost = (1.0 - p_a) + (1.0 - p_b)  # capital deployed: cost of both NO legs
        gross = p_a + p_b - 1.0
        friction = self._friction_cost(total_cost)
        net = gross - friction

        if net <= 0:
            return None

        legs = [
            Leg(market_id=a.id, side="NO", price=1.0 - p_a, platform=a.platform),
            Leg(market_id=b.id, side="NO", price=1.0 - p_b, platform=b.platform),
        ]
        return PayoffMatrix(
            legs=legs,
            total_cost=total_cost,
            scenarios=[
                Scenario(name="A resolves YES", description="A pays out, B expires worthless", payoff=net, is_breaking=False),
                Scenario(name="B resolves YES", description="B pays out, A expires worthless", payoff=net, is_breaking=False),
            ],
            worst_case_payoff=net,
            best_case_payoff=net,
            breaking_scenario=None,
            opportunity_type=OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING,
            friction_bps=self._friction_bps,
        )

    def _score_candidate(self, a: RawMarket, b: RawMarket, relation) -> RiskScore:
        relation_type = RelationType(relation.relation_type if hasattr(relation, "relation_type") else relation["relation_type"])
        relation_signals = get_relation_signals(relation)
        semantic_confidence_value = (
            relation.semantic_confidence
            if hasattr(relation, "semantic_confidence")
            else relation.get("evidence", {}).get("semantic_confidence")
        )
        semantic_confidence = (
            float(semantic_confidence_value)
            if isinstance(semantic_confidence_value, (int, float))
            else float(relation.confidence if hasattr(relation, "confidence") else relation.get("confidence", 0.5))
        )
        semantic_risk = round(max(0.0, min(1.0, 1.0 - semantic_confidence)), 4)
        if relation_signals["ambiguity_level"] == "high":
            semantic_risk = min(1.0, round(semantic_risk + 0.2, 4))
        elif relation_signals["ambiguity_level"] == "medium":
            semantic_risk = min(1.0, round(semantic_risk + 0.1, 4))

        if relation_type == RelationType.MUTUALLY_EXCLUSIVE:
            oracle_risk = 0.05
        else:
            oracle_risk = 0.2 if a.platform != b.platform else 0.1
        if relation_signals["oracle_mismatch"]:
            oracle_risk = min(1.0, round(oracle_risk + 0.3, 4))

        deadline_delta_days = abs((a.deadline - b.deadline).total_seconds()) / 86400
        deadline_risk = round(min(1.0, deadline_delta_days / 14.0), 4)
        if relation_signals["deadline_mismatch"]:
            deadline_risk = min(1.0, round(deadline_risk + 0.15, 4))

        execution_risk = 0.1 if a.platform != b.platform else 0.05
        if relation_type in {
            RelationType.EQUIVALENT,
            RelationType.DUPLICATE,
            RelationType.SUBSET,
            RelationType.SUPERSET,
        }:
            execution_risk = round(execution_risk + 0.08, 4)

        liquidity_risk = 0.12 if a.platform != b.platform else 0.08
        cross_platform_spread = abs(float(a.outcome_prices[0]) - float(b.outcome_prices[0]))
        if cross_platform_spread >= 0.15:
            liquidity_risk = min(1.0, round(liquidity_risk + 0.08, 4))

        cancellation_risk = 0.05
        if any(
            term in " ".join(relation_signals.get("ambiguity_terms", [])).lower()
            for term in ("void", "cancel", "official", "certif")
        ):
            cancellation_risk = 0.18

        source_trust_risk = 0.08 if a.platform == b.platform else 0.16
        if relation_signals["source_mismatch"] or relation_signals["oracle_mismatch"]:
            source_trust_risk = min(1.0, round(source_trust_risk + 0.18, 4))

        return RiskScore.combine(
            oracle=round(oracle_risk, 4),
            deadline=deadline_risk,
            semantic=semantic_risk,
            execution=round(execution_risk, 4),
            liquidity=round(liquidity_risk, 4),
            cancellation=round(cancellation_risk, 4),
            source_trust=round(source_trust_risk, 4),
        )

    def _check_equivalent(
        self, a: RawMarket, b: RawMarket
    ) -> PayoffMatrix | None:
        """Buy YES on cheaper platform, buy NO (sell YES) on more expensive.

        For truly EQUIVALENT markets both legs resolve the same way, so the
        spread (sell_price - buy_price) is realised regardless of outcome.
        total_cost = buy_price + (1 - sell_price); payoff is direction-neutral.
        worst_case_payoff is already post-friction; SimulatorService must NOT
        re-apply friction.
        """
        if not a.outcome_prices or not b.outcome_prices:
            return None
        p_a = a.outcome_prices[0]
        p_b = b.outcome_prices[0]
        if not isinstance(p_a, (int, float)) or not isinstance(p_b, (int, float)):
            return None
        if abs(p_a - p_b) < 0.01:
            return None

        if p_a < p_b:
            buyer, seller = a, b
            buy_price, sell_price = p_a, p_b
        else:
            buyer, seller = b, a
            buy_price, sell_price = p_b, p_a

        # Capital deployed: cost of YES leg + cost of NO leg
        total_cost = buy_price + (1.0 - sell_price)
        gross = sell_price - buy_price  # same payoff regardless of YES/NO outcome
        friction = self._friction_cost(total_cost)
        net = gross - friction

        if net <= 0:
            return None

        legs = [
            Leg(market_id=buyer.id, side="YES", price=buy_price, platform=buyer.platform),
            Leg(market_id=seller.id, side="NO", price=1.0 - sell_price, platform=seller.platform),
        ]
        return PayoffMatrix(
            legs=legs,
            total_cost=total_cost,
            scenarios=[
                Scenario(name="Event resolves YES", description="YES leg wins, NO leg expires worthless", payoff=net, is_breaking=False),
                Scenario(name="Event resolves NO", description="NO leg wins, YES leg expires worthless", payoff=net, is_breaking=False),
            ],
            worst_case_payoff=net,
            best_case_payoff=net,
            breaking_scenario=None,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            friction_bps=self._friction_bps,
        )
