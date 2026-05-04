from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.candidates.evidence import load_relation_evidence
from parallax.candidates.repository import CandidateRepository
from parallax.db.models import RawMarket
from parallax.graph.repository import GraphRepository
from parallax.shared.relation_signals import get_relation_signals
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    RiskScore,
    RelationType,
)
from parallax.solver.service import GeneralizedPayoffSolver

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
        self._solver = GeneralizedPayoffSolver(friction_bps=friction_bps)

    def scan(self, markets: list[RawMarket]) -> int:
        """Check all relations for profitable divergences. Returns count of new candidates."""
        market_map = {m.id: m for m in markets}
        found = 0
        seen_pairs: set[frozenset[str]] = set()
        processed_sets: set[str] = set()

        for relation_set in self._list_tradeable_relation_sets():
            member_ids = [market_id for market_id in relation_set.member_market_ids if market_id in market_map]
            if len(member_ids) < 2 or relation_set.set_key in processed_sets:
                continue
            relation_evidence = load_relation_evidence(self._session, member_ids)
            if relation_evidence is None:
                continue
            result = self._solve_candidate(
                [market_map[market_id] for market_id in member_ids],
                relation_evidence=relation_evidence,
                relation_sets=[relation_set],
                relations=[],
            )
            if result is None:
                continue
            if self._persist_candidate([market_map[market_id] for market_id in member_ids], relation_evidence, result):
                found += 1
                processed_sets.add(relation_set.set_key)

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

                result = self._solve_candidate(
                    [market_map[a_id], market_map[b_id]],
                    relation_evidence=relation_evidence,
                    relation_sets=[],
                    relations=[self._relation_dict_to_schema(rel)],
                )
                if result is None:
                    continue
                if self._persist_candidate([market_map[a_id], market_map[b_id]], relation_evidence, result):
                    found += 1

        return found

    def _persist_candidate(self, markets: list[RawMarket], relation_evidence, result) -> bool:
        market_ids = [market.id for market in markets]
        matrix = result.payoff_matrix
        if matrix.worst_case_payoff <= _MIN_PROFIT_AFTER_FRICTION:
            return False
        if result.false_arbitrage_label is not None:
            return False
        if self._candidate_repo.candidate_exists(
            market_ids,
            matrix.opportunity_type,
            constraint_fingerprint=result.constraint_fingerprint,
            solver_version=result.solver_version,
        ):
            return False
        risk_score = (
            self._score_candidate(markets[0], markets[1], relation_evidence)
            if len(markets) >= 2
            else RiskScore.combine(oracle=0.5, deadline=0.5, semantic=0.5)
        )
        self._candidate_repo.create(
            market_ids=market_ids,
            payoff_matrix=matrix,
            opportunity_type=matrix.opportunity_type,
            risk_scores=risk_score.model_dump(),
            scenario_matrix=result.scenario_matrix,
            proof_object=result.proof_object,
            solver_version=result.solver_version,
            constraint_fingerprint=result.constraint_fingerprint,
            basket=result.basket,
            false_arbitrage_label=result.false_arbitrage_label,
            audit_record=result.audit_record,
        )
        return True

    def _solve_candidate(
        self,
        markets: list[RawMarket],
        *,
        relation_evidence,
        relation_sets: list[LogicalRelationSetSchema],
        relations: list[LogicalRelationSchema],
    ):
        return self._solver.solve(
            markets=markets,
            relation_evidence=relation_evidence,
            relation_sets=relation_sets,
            relations=relations,
        )

    def _list_tradeable_relation_sets(self) -> list[LogicalRelationSetSchema]:
        if not hasattr(self._graph_repo, "list_relation_sets"):
            return []
        rows = self._graph_repo.list_relation_sets(limit=500)
        if not isinstance(rows, list):
            return []
        result: list[LogicalRelationSetSchema] = []
        for row in rows:
            try:
                schema = LogicalRelationSetSchema(
                    relation_set_id=row.get("id"),
                    set_key=row["set_key"],
                    member_market_ids=row.get("member_market_ids", []),
                    relation_type=RelationType(row["relation_type"]),
                    proof_status=row.get("proof_status", "verified"),
                    tradeable_relation=bool(row.get("tradeable_relation", False)),
                    confidence=row.get("confidence", 0.0),
                    created_by=row.get("created_by", "unknown"),
                    evidence=row.get("evidence", {}),
                    frame_id=row.get("frame_id"),
                )
            except Exception:
                continue
            if schema.tradeable_relation and schema.proof_status == "verified":
                result.append(schema)
        return result

    @staticmethod
    def _relation_dict_to_schema(rel: dict) -> LogicalRelationSchema:
        return LogicalRelationSchema(
            from_market_id=rel["from_market_id"],
            to_market_id=rel["to_market_id"],
            relation_type=RelationType(rel["relation_type"]),
            proof_status=rel.get("proof_status", "verified"),
            tradeable_relation=bool(rel.get("tradeable_relation", False)),
            confidence=rel.get("confidence", 0.0),
            created_by=rel.get("created_by", "unknown"),
            evidence=rel.get("evidence", {}),
            frame_id=rel.get("frame_id"),
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
