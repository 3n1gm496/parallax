from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.db.models import RawMarket
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.graph.repository import GraphRepository
from parallax.shared.schemas import (
    Leg,
    OpportunityType,
    PayoffMatrix,
    RelationType,
    Scenario,
)

_DEFAULT_FRICTION_BPS = 20
_MIN_PROFIT_AFTER_FRICTION = 0.005  # 0.5% minimum edge


class DivergenceService:
    """Detect pricing divergences and emit OpportunityCandidate records."""

    def __init__(
        self,
        session: Session,
        graph_repo: GraphRepository,
        friction_bps: int = _DEFAULT_FRICTION_BPS,
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
                    self._candidate_repo.create(
                        market_ids=[a_id, b_id],
                        payoff_matrix=matrix,
                        opportunity_type=matrix.opportunity_type,
                        risk_scores={},
                    )
                    found += 1

        return found

    def _friction_cost(self, total_cost: float) -> float:
        return total_cost * self._friction_bps / 10_000

    def _check_mutually_exclusive(
        self, a: RawMarket, b: RawMarket
    ) -> PayoffMatrix | None:
        """Sell YES on both legs. Profit if sum of YES prices > 1 + friction."""
        p_a = a.outcome_prices[0]  # YES price for market A
        p_b = b.outcome_prices[0]  # YES price for market B
        proceeds = p_a + p_b
        total_cost = 1.0  # one leg always pays out 1.0
        friction = self._friction_cost(total_cost)
        net = proceeds - total_cost - friction

        if net <= 0:
            return None

        legs = [
            Leg(market_id=a.id, side="NO", price=1 - p_a, platform=a.platform),
            Leg(market_id=b.id, side="NO", price=1 - p_b, platform=b.platform),
        ]
        return PayoffMatrix(
            legs=legs,
            total_cost=total_cost,
            scenarios=[
                Scenario(name="A resolves YES", description="A wins, B loses", payoff=net, is_breaking=False),
                Scenario(name="B resolves YES", description="B wins, A loses", payoff=net, is_breaking=False),
            ],
            worst_case_payoff=net,
            best_case_payoff=net,
            breaking_scenario=None,
            opportunity_type=OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING,
            friction_bps=self._friction_bps,
        )

    def _check_equivalent(
        self, a: RawMarket, b: RawMarket
    ) -> PayoffMatrix | None:
        """Buy cheaper YES, sell more expensive YES (cross-platform spread)."""
        p_a = a.outcome_prices[0]
        p_b = b.outcome_prices[0]
        if abs(p_a - p_b) < 0.01:
            return None

        if p_a < p_b:
            buyer, seller = a, b
            buy_price, sell_price = p_a, p_b
        else:
            buyer, seller = b, a
            buy_price, sell_price = p_b, p_a

        total_cost = buy_price
        friction = self._friction_cost(total_cost)
        net = sell_price - buy_price - friction

        if net <= 0:
            return None

        legs = [
            Leg(market_id=buyer.id, side="YES", price=buy_price, platform=buyer.platform),
            Leg(market_id=seller.id, side="NO", price=1 - sell_price, platform=seller.platform),
        ]
        return PayoffMatrix(
            legs=legs,
            total_cost=total_cost,
            scenarios=[
                Scenario(name="Event resolves YES", description="Buy leg wins, sell leg loses net", payoff=net, is_breaking=False),
                Scenario(name="Event resolves NO", description="Both legs net", payoff=-buy_price + (1 - sell_price) - friction, is_breaking=True),
            ],
            worst_case_payoff=net,
            best_case_payoff=net,
            breaking_scenario=None,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            friction_bps=self._friction_bps,
        )
