from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations

from sqlalchemy.orm import Session

from parallax.candidates.evidence import load_relation_evidence
from parallax.config import settings
from parallax.db.models import (
    CompiledContract,
    EventIdentityCluster,
    IdentityClusterMember,
    IdentityMatchReview,
    LogicalRelation,
    LogicalRelationSet,
    OpportunityCandidate,
    RawMarket,
    RelationReview,
    RunProofRecord,
    ShadowCandidateObservation,
    VenueToken,
)
from parallax.divergence.service import _MIN_PROFIT_AFTER_FRICTION
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.ops.schemas import (
    CandidateFunnelCompilationReport,
    CandidateFunnelIdentityReport,
    CandidateFunnelMarketsReport,
    CandidateFunnelPersistenceReport,
    CandidateFunnelPreviewReport,
    CandidateFunnelRelationReport,
    CandidateFunnelReport,
    CandidateFunnelSolverReport,
    CountWithPct,
    ReasonCount,
    SensitivityBucket,
    SensitivityReport,
    ShadowCandidateListResponse,
    ShadowCandidateRow,
    SolverDecisionEntry,
)
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    RelationEvidenceResponse,
    RelationType,
)
from parallax.solver.service import GeneralizedPayoffSolver, SolverDecision


_RELAXATION_KEYS = (
    "identity_gate_relaxed",
    "semantic_gate_relaxed",
    "min_profit_threshold_relaxed",
    "execution_gate_relaxed",
    "dedup_disabled",
)

_DANGEROUS_RELAXATIONS = {"identity_gate_relaxed", "semantic_gate_relaxed"}


@dataclass(slots=True)
class _VariantOutcome:
    relation_evidence: RelationEvidenceResponse | None
    decision: SolverDecision | None


class CandidateDiagnosticsService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._graph_repo = PostgresGraphRepository(session)
        self._solver = GeneralizedPayoffSolver(
            friction_bps=settings.friction_bps,
            session=session,
        )

    def rebuild_for_run(self, run_id: str, markets: list[RawMarket]) -> int:
        self._session.query(ShadowCandidateObservation).filter(
            ShadowCandidateObservation.run_id == run_id
        ).delete(synchronize_session=False)
        market_map = {market.id: market for market in markets}
        observations: list[ShadowCandidateObservation] = []

        for relation_set in self._list_all_relation_sets():
            member_ids = [market_id for market_id in relation_set.member_market_ids if market_id in market_map]
            if len(member_ids) < 2:
                continue
            relation_evidence = load_relation_evidence(self._session, member_ids)
            observations.append(
                self._build_observation(
                    run_id=run_id,
                    relation_key=relation_set.set_key,
                    relation_kind="relation_set",
                    relation_type=relation_set.relation_type.value,
                    markets=[market_map[market_id] for market_id in member_ids],
                    relation_evidence=relation_evidence,
                    relation_sets=[relation_set],
                    relations=[],
                    metadata={"frame_id": relation_set.frame_id},
                )
            )

        seen_relation_ids: set[str] = set()
        for market in markets:
            for rel in self._graph_repo.get_relations(market.id):
                relation_id = str(rel.get("id") or "")
                if not relation_id or relation_id in seen_relation_ids:
                    continue
                seen_relation_ids.add(relation_id)
                market_ids = [rel["from_market_id"], rel["to_market_id"]]
                if any(market_id not in market_map for market_id in market_ids):
                    continue
                relation_evidence = load_relation_evidence(self._session, market_ids)
                observations.append(
                    self._build_observation(
                        run_id=run_id,
                        relation_key=relation_id,
                        relation_kind="relation",
                        relation_type=str(rel["relation_type"]),
                        markets=[market_map[market_id] for market_id in market_ids],
                        relation_evidence=relation_evidence,
                        relation_sets=[],
                        relations=[self._relation_dict_to_schema(rel)],
                        metadata={"frame_id": rel.get("frame_id")},
                    )
                )

        self._session.add_all(observations)
        self._session.flush()
        return len(observations)

    def build_candidate_funnel_report(self, run_id: str | None = None) -> CandidateFunnelReport:
        resolved_run_id = self.resolve_run_id(run_id)
        observations = self._list_observations(resolved_run_id)
        markets = self._build_markets_report(resolved_run_id)
        compilation = self._build_compilation_report(markets.total)
        identity = self._build_identity_report(markets.total)
        relations = self._build_relation_report(observations)
        solver = self._build_solver_report(observations)
        persistence = self._build_persistence_report(observations)
        preview = self._build_preview_report(observations)
        top_blockers = self._reason_rows(
            Counter(
                reason
                for observation in observations
                for reason in (observation.blocking_gates or [])
            ),
            limit=10,
        )
        return CandidateFunnelReport(
            run_id=resolved_run_id,
            generated_at=datetime.now(timezone.utc),
            markets=markets,
            compilation=compilation,
            identity=identity,
            relations=relations,
            solver=solver,
            persistence=persistence,
            preview=preview,
            top_blockers=top_blockers,
        )

    def build_shadow_candidates_report(
        self,
        run_id: str | None = None,
        *,
        limit: int = 20,
    ) -> ShadowCandidateListResponse:
        resolved_run_id = self.resolve_run_id(run_id)
        observations = sorted(
            self._list_observations(resolved_run_id),
            key=lambda item: (
                0 if item.persisted_candidate_id is None else 1,
                -(item.displayed_edge or -999.0),
                -(item.executable_edge or -999.0),
            ),
        )
        rows = [
            ShadowCandidateRow(
                observation_id=str(item.id),
                run_id=item.run_id,
                relation_key=item.relation_key,
                relation_kind=item.relation_kind,
                relation_type=item.relation_type,
                market_ids=list(item.market_ids or []),
                displayed_edge=item.displayed_edge,
                executable_edge=item.executable_edge,
                worst_case_payoff=item.worst_case_payoff,
                blocking_gates=list(item.blocking_gates or []),
                minimal_relaxation=list(item.minimal_relaxation or []),
                dangerous_relaxation=bool(item.dangerous_relaxation),
                relaxation_flags={
                    key: bool((item.relaxation_flags or {}).get(key, False))
                    for key in _RELAXATION_KEYS
                },
                identity_status=item.identity_status,
                proof_status=item.proof_status,
                tradeable_relation=bool(item.tradeable_relation),
                false_arbitrage_label=item.false_arbitrage_label,
                rejected_by_threshold=bool(item.rejected_by_threshold),
                rejected_by_dedup=bool(item.rejected_by_dedup),
                execution_evidence_missing=bool(item.execution_evidence_missing),
                metadata=dict(item.metadata_json or {}),
            )
            for item in observations[:limit]
        ]
        return ShadowCandidateListResponse(
            run_id=resolved_run_id,
            generated_at=datetime.now(timezone.utc),
            total=len(observations),
            rows=rows,
        )

    def build_sensitivity_report(self, run_id: str | None = None) -> SensitivityReport:
        resolved_run_id = self.resolve_run_id(run_id)
        observations = self._list_observations(resolved_run_id)
        current_semantic = settings.semantic_min_relation_confidence
        return SensitivityReport(
            run_id=resolved_run_id,
            generated_at=datetime.now(timezone.utc),
            min_profit_thresholds=[
                SensitivityBucket(label="0 bps", count=self._count_threshold(observations, 0)),
                SensitivityBucket(label="10 bps", count=self._count_threshold(observations, 10)),
                SensitivityBucket(label="25 bps", count=self._count_threshold(observations, 25)),
                SensitivityBucket(label="50 bps", count=self._count_threshold(observations, 50)),
                SensitivityBucket(label="100 bps", count=self._count_threshold(observations, 100)),
            ],
            identity_gates=[
                SensitivityBucket(label="verified only", count=self._count_identity(observations, {"verified"})),
                SensitivityBucket(
                    label="verified or ambiguous",
                    count=self._count_identity(observations, {"verified", "ambiguous"}),
                ),
                SensitivityBucket(
                    label="any non-rejected",
                    count=self._count_identity(observations, {"verified", "ambiguous", "unresolved"}),
                ),
            ],
            semantic_thresholds=[
                SensitivityBucket(label=f"{current_semantic:.2f}", count=self._count_semantic_tradeable(current_semantic)),
                SensitivityBucket(
                    label=f"{max(0.0, current_semantic - 0.1):.2f}",
                    count=self._count_semantic_tradeable(max(0.0, current_semantic - 0.1)),
                ),
                SensitivityBucket(
                    label=f"{max(0.0, current_semantic - 0.2):.2f}",
                    count=self._count_semantic_tradeable(max(0.0, current_semantic - 0.2)),
                ),
            ],
            execution_modes=[
                SensitivityBucket(label="block", count=self._count_execution_mode(observations, mode="block")),
                SensitivityBucket(label="degraded", count=self._count_execution_mode(observations, mode="degraded")),
                SensitivityBucket(
                    label="historical fallback",
                    count=self._count_execution_mode(observations, mode="heuristic_fallback"),
                ),
            ],
        )

    def resolve_run_id(self, run_id: str | None) -> str:
        if run_id:
            return run_id
        row = (
            self._session.query(RunProofRecord)
            .filter(RunProofRecord.run_status != "running")
            .order_by(RunProofRecord.completed_at.desc(), RunProofRecord.started_at.desc())
            .first()
        )
        if row is None:
            raise ValueError("No completed run proof found")
        return row.run_id

    def _list_observations(self, run_id: str) -> list[ShadowCandidateObservation]:
        return (
            self._session.query(ShadowCandidateObservation)
            .filter(ShadowCandidateObservation.run_id == run_id)
            .order_by(ShadowCandidateObservation.created_at.asc())
            .all()
        )

    def _list_all_relation_sets(self) -> list[LogicalRelationSetSchema]:
        rows = self._graph_repo.list_relation_sets(limit=5000)
        result: list[LogicalRelationSetSchema] = []
        for row in rows:
            try:
                result.append(
                    LogicalRelationSetSchema(
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
                )
            except Exception:
                continue
        return result

    def _build_observation(
        self,
        *,
        run_id: str,
        relation_key: str,
        relation_kind: str,
        relation_type: str,
        markets: list[RawMarket],
        relation_evidence: RelationEvidenceResponse | None,
        relation_sets: list[LogicalRelationSetSchema],
        relations: list[LogicalRelationSchema],
        metadata: dict[str, object],
    ) -> ShadowCandidateObservation:
        base_variant = self._run_variant(
            relation_evidence=relation_evidence,
            markets=markets,
            relation_sets=relation_sets,
            relations=relations,
            relax_identity=False,
            relax_semantic=False,
        )
        identity_variant = self._run_variant(
            relation_evidence=relation_evidence,
            markets=markets,
            relation_sets=relation_sets,
            relations=relations,
            relax_identity=True,
            relax_semantic=False,
        )
        semantic_variant = self._run_variant(
            relation_evidence=relation_evidence,
            markets=markets,
            relation_sets=relation_sets,
            relations=relations,
            relax_identity=False,
            relax_semantic=True,
        )
        both_variant = self._run_variant(
            relation_evidence=relation_evidence,
            markets=markets,
            relation_sets=relation_sets,
            relations=relations,
            relax_identity=True,
            relax_semantic=True,
        )
        production = self._evaluate_production_candidate(base_variant, markets)
        relax_flags = self._build_relaxation_flags(
            base_variant=base_variant,
            identity_variant=identity_variant,
            semantic_variant=semantic_variant,
            both_variant=both_variant,
            production=production,
            markets=markets,
        )
        minimal_relaxation = self._minimal_relaxation(
            base_variant=base_variant,
            identity_variant=identity_variant,
            semantic_variant=semantic_variant,
            both_variant=both_variant,
            production=production,
        )
        diagnostics = base_variant.decision.diagnostics if base_variant.decision is not None else None
        persisted_candidate = production.get("persisted_candidate")
        return ShadowCandidateObservation(
            run_id=run_id,
            relation_key=relation_key,
            relation_kind=relation_kind,
            relation_type=relation_type,
            market_ids=[market.id for market in markets],
            identity_status=(
                relation_evidence.identity_status.value
                if relation_evidence is not None
                else IdentityResolutionStatus.UNRESOLVED.value
            ),
            identity_version=relation_evidence.identity_version if relation_evidence is not None else "identity-v1",
            proof_status=relation_evidence.proof_status if relation_evidence is not None else "needs_review",
            tradeable_relation=bool(relation_evidence.tradeable_relation) if relation_evidence is not None else False,
            solver_called=bool(diagnostics.solver_called) if diagnostics is not None else False,
            solver_skip_reason=str(production.get("solver_skip_reason")) if production.get("solver_skip_reason") else None,
            solver_none_reason=(
                diagnostics.solver_none_reason
                if diagnostics is not None and diagnostics.solver_none_reason
                else None
            ),
            displayed_edge=diagnostics.displayed_edge if diagnostics is not None else None,
            executable_edge=diagnostics.executable_edge if diagnostics is not None else None,
            worst_case_payoff=(
                base_variant.decision.result.payoff_matrix.worst_case_payoff
                if base_variant.decision is not None and base_variant.decision.result is not None
                else None
            ),
            valid_state_count=diagnostics.valid_state_count if diagnostics is not None else 0,
            impossible_state_count=diagnostics.impossible_state_count if diagnostics is not None else 0,
            false_arbitrage_label=(
                diagnostics.false_arbitrage_label if diagnostics is not None else None
            ),
            min_profit_threshold=_MIN_PROFIT_AFTER_FRICTION,
            rejected_by_threshold=bool(production["rejected_by_threshold"]),
            rejected_by_identity=bool(production["rejected_by_identity"]),
            rejected_by_false_arbitrage=bool(production["rejected_by_false_arbitrage"]),
            rejected_by_dedup=bool(production["rejected_by_dedup"]),
            execution_evidence_missing=not bool(
                diagnostics.executable_pricing_used if diagnostics is not None else False
            ),
            blocking_gates=list(production["blocking_gates"]),
            relaxation_flags=relax_flags,
            minimal_relaxation=minimal_relaxation,
            dangerous_relaxation=any(item in _DANGEROUS_RELAXATIONS for item in minimal_relaxation),
            persisted_candidate_id=persisted_candidate.id if persisted_candidate is not None else None,
            metadata_json={
                **metadata,
                "semantic_confidence": (
                    relation_evidence.semantic_confidence if relation_evidence is not None else None
                ),
                "current_threshold_bps": int(_MIN_PROFIT_AFTER_FRICTION * 10_000),
            },
        )

    def _evaluate_production_candidate(
        self,
        variant: _VariantOutcome,
        markets: list[RawMarket],
    ) -> dict[str, object]:
        blocking_gates: list[str] = []
        solver_skip_reason: str | None = None
        rejected_by_identity = False
        rejected_by_false_arbitrage = False
        rejected_by_threshold = False
        rejected_by_dedup = False
        persisted_candidate = None

        evidence = variant.relation_evidence
        if evidence is None:
            solver_skip_reason = "missing_relation_evidence"
            blocking_gates.append("missing_relation_evidence")
        elif evidence.identity_status != IdentityResolutionStatus.VERIFIED:
            solver_skip_reason = "identity_not_verified"
            blocking_gates.append("identity_gate")
            rejected_by_identity = True
        elif not evidence.tradeable_relation:
            solver_skip_reason = "relation_not_tradeable"
            blocking_gates.append("semantic_gate")
        elif str(evidence.proof_status) != "verified":
            solver_skip_reason = "proof_not_verified"
            blocking_gates.append("semantic_gate")
        elif variant.decision is None or variant.decision.result is None:
            solver_skip_reason = (
                variant.decision.diagnostics.solver_none_reason
                if variant.decision is not None
                else "solver_not_invoked"
            )
            blocking_gates.append("solver_no_solution")
        else:
            result = variant.decision.result
            if result.payoff_matrix.worst_case_payoff <= _MIN_PROFIT_AFTER_FRICTION:
                rejected_by_threshold = True
                blocking_gates.append("min_profit_threshold")
            elif result.false_arbitrage_label is not None:
                rejected_by_false_arbitrage = True
                blocking_gates.append("false_arbitrage_gate")
            else:
                persisted_candidate = (
                    self._session.query(OpportunityCandidate)
                    .filter(
                        OpportunityCandidate.status == "open",
                        OpportunityCandidate.constraint_fingerprint == result.constraint_fingerprint,
                        OpportunityCandidate.solver_version == result.solver_version,
                    )
                    .first()
                )
                if persisted_candidate is None:
                    rejected_by_dedup = True
                    blocking_gates.append("dedup_gate")
                else:
                    blocking_gates.append("persisted")

        return {
            "blocking_gates": [item for item in blocking_gates if item != "persisted"],
            "solver_skip_reason": solver_skip_reason,
            "rejected_by_identity": rejected_by_identity,
            "rejected_by_false_arbitrage": rejected_by_false_arbitrage,
            "rejected_by_threshold": rejected_by_threshold,
            "rejected_by_dedup": rejected_by_dedup,
            "persisted_candidate": persisted_candidate,
        }

    def _build_relaxation_flags(
        self,
        *,
        base_variant: _VariantOutcome,
        identity_variant: _VariantOutcome,
        semantic_variant: _VariantOutcome,
        both_variant: _VariantOutcome,
        production: dict[str, object],
        markets: list[RawMarket],
    ) -> dict[str, bool]:
        flags = {key: False for key in _RELAXATION_KEYS}
        flags["identity_gate_relaxed"] = self._qualifies_as_candidate(identity_variant, ignore_dedup=False)
        flags["semantic_gate_relaxed"] = self._qualifies_as_candidate(semantic_variant, ignore_dedup=False)
        base_decision = base_variant.decision
        if base_decision is not None and base_decision.result is not None:
            flags["min_profit_threshold_relaxed"] = (
                base_decision.result.payoff_matrix.worst_case_payoff > 0
                and not bool(production["rejected_by_false_arbitrage"])
                and not bool(production["rejected_by_dedup"])
            )
            flags["execution_gate_relaxed"] = (
                base_decision.result.payoff_matrix.worst_case_payoff > _MIN_PROFIT_AFTER_FRICTION
                and base_decision.result.false_arbitrage_label is None
                and not base_decision.diagnostics.executable_pricing_used
            )
        flags["dedup_disabled"] = bool(production["rejected_by_dedup"])
        if not any(flags.values()) and self._qualifies_as_candidate(both_variant, ignore_dedup=False):
            flags["identity_gate_relaxed"] = True
            flags["semantic_gate_relaxed"] = True
        return flags

    def _minimal_relaxation(
        self,
        *,
        base_variant: _VariantOutcome,
        identity_variant: _VariantOutcome,
        semantic_variant: _VariantOutcome,
        both_variant: _VariantOutcome,
        production: dict[str, object],
    ) -> list[str]:
        if production["persisted_candidate"] is not None:
            return []

        def variant_for(selected: set[str]) -> _VariantOutcome:
            if "identity_gate_relaxed" in selected and "semantic_gate_relaxed" in selected:
                return both_variant
            if "identity_gate_relaxed" in selected:
                return identity_variant
            if "semantic_gate_relaxed" in selected:
                return semantic_variant
            return base_variant

        for size in range(1, len(_RELAXATION_KEYS) + 1):
            for items in combinations(_RELAXATION_KEYS, size):
                selected = set(items)
                candidate = self._qualifies_as_candidate(
                    variant_for(selected),
                    ignore_dedup="dedup_disabled" in selected,
                    relax_threshold="min_profit_threshold_relaxed" in selected,
                    relax_execution="execution_gate_relaxed" in selected,
                )
                if candidate:
                    return list(items)
        return []

    def _qualifies_as_candidate(
        self,
        variant: _VariantOutcome,
        *,
        ignore_dedup: bool,
        relax_threshold: bool = False,
        relax_execution: bool = True,
    ) -> bool:
        if variant.decision is None or variant.decision.result is None:
            return False
        result = variant.decision.result
        if result.false_arbitrage_label is not None:
            return False
        threshold = 0.0 if relax_threshold else _MIN_PROFIT_AFTER_FRICTION
        if result.payoff_matrix.worst_case_payoff <= threshold:
            return False
        if not relax_execution and not variant.decision.diagnostics.executable_pricing_used:
            return False
        if ignore_dedup:
            return True
        return (
            self._session.query(OpportunityCandidate)
            .filter(
                OpportunityCandidate.status == "open",
                OpportunityCandidate.constraint_fingerprint == result.constraint_fingerprint,
                OpportunityCandidate.solver_version == result.solver_version,
            )
            .first()
        ) is not None

    def _run_variant(
        self,
        *,
        relation_evidence: RelationEvidenceResponse | None,
        markets: list[RawMarket],
        relation_sets: list[LogicalRelationSetSchema],
        relations: list[LogicalRelationSchema],
        relax_identity: bool,
        relax_semantic: bool,
    ) -> _VariantOutcome:
        effective_evidence = self._relaxed_relation_evidence(
            relation_evidence,
            relax_identity=relax_identity,
            relax_semantic=relax_semantic,
        )
        effective_sets = self._relaxed_relation_sets(relation_sets, relax_semantic=relax_semantic)
        effective_relations = self._relaxed_relations(relations, relax_semantic=relax_semantic)
        if effective_evidence is None:
            return _VariantOutcome(relation_evidence=None, decision=None)
        should_call_solver = (
            relax_identity
            or relax_semantic
            or (
                effective_evidence.identity_status == IdentityResolutionStatus.VERIFIED
                and effective_evidence.tradeable_relation
                and str(effective_evidence.proof_status) == "verified"
            )
        )
        if not should_call_solver:
            return _VariantOutcome(relation_evidence=effective_evidence, decision=None)
        return _VariantOutcome(
            relation_evidence=effective_evidence,
            decision=self._solver.solve_with_trace(
                markets=markets,
                relation_evidence=effective_evidence,
                relation_sets=effective_sets,
                relations=effective_relations,
            ),
        )

    @staticmethod
    def _relaxed_relation_evidence(
        relation_evidence: RelationEvidenceResponse | None,
        *,
        relax_identity: bool,
        relax_semantic: bool,
    ) -> RelationEvidenceResponse | None:
        if relation_evidence is None:
            return None
        updates: dict[str, object] = {}
        if relax_identity:
            updates["identity_status"] = IdentityResolutionStatus.VERIFIED
            updates["identity_version"] = "identity-v3-runtime-shadow"
            updates["identity_blocking_reason"] = None
        if relax_semantic:
            updates["tradeable_relation"] = True
            updates["proof_status"] = "verified"
            updates["is_confirmed"] = True
            updates["abstention_reason"] = None
        if not updates:
            return relation_evidence
        return relation_evidence.model_copy(update=updates)

    @staticmethod
    def _relaxed_relation_sets(
        relation_sets: list[LogicalRelationSetSchema],
        *,
        relax_semantic: bool,
    ) -> list[LogicalRelationSetSchema]:
        if not relax_semantic:
            return relation_sets
        return [
            item.model_copy(update={"tradeable_relation": True, "proof_status": "verified"})
            for item in relation_sets
        ]

    @staticmethod
    def _relaxed_relations(
        relations: list[LogicalRelationSchema],
        *,
        relax_semantic: bool,
    ) -> list[LogicalRelationSchema]:
        if not relax_semantic:
            return relations
        return [
            item.model_copy(update={"tradeable_relation": True, "proof_status": "verified"})
            for item in relations
        ]

    def _build_markets_report(self, run_id: str) -> CandidateFunnelMarketsReport:
        run = self._session.get(RunProofRecord, run_id)
        markets = self._session.query(RawMarket).all()
        total = run.markets_ingested if run is not None and run.markets_ingested else len(markets)
        compiled_market_ids = {
            raw_market_id for (raw_market_id,) in self._session.query(CompiledContract.raw_market_id).distinct().all()
        }
        token_market_ids = {
            raw_market_id for (raw_market_id,) in self._session.query(VenueToken.raw_market_id).distinct().all()
        }
        open_count = sum(1 for market in markets if not market.is_closed)
        closed_count = len(markets) - open_count
        outcome_prices_count = sum(
            1 for market in markets if isinstance(market.outcome_prices, list) and len(market.outcome_prices) >= 2
        )
        token_count = sum(1 for market in markets if market.id in token_market_ids)
        deadline_count = sum(1 for market in markets if market.deadline is not None)
        compiled_count = sum(1 for market in markets if market.id in compiled_market_ids)
        return CandidateFunnelMarketsReport(
            total=total,
            by_platform=dict((run.market_counts_by_platform if run is not None else {}) or {}),
            open=self._count_with_pct(open_count, total),
            closed=self._count_with_pct(closed_count, total),
            with_outcome_prices=self._count_with_pct(outcome_prices_count, total),
            with_token_ids=self._count_with_pct(token_count, total),
            with_usable_deadlines=self._count_with_pct(deadline_count, total),
            with_compiled_contracts=self._count_with_pct(compiled_count, total),
        )

    def _build_compilation_report(self, total_markets: int) -> CandidateFunnelCompilationReport:
        rows = self._session.query(CompiledContract).all()
        compiled_count = len({row.raw_market_id for row in rows})
        below_confidence = 0
        missing_fields = 0
        for row in rows:
            contract = row.contract_json or {}
            if float(row.compiler_confidence or 0.0) < settings.compiler_min_confidence:
                below_confidence += 1
            if (
                not contract.get("yes_conditions")
                or not contract.get("no_conditions")
                or not contract.get("temporal_deadline")
            ):
                missing_fields += 1
        return CandidateFunnelCompilationReport(
            compiled=self._count_with_pct(compiled_count, total_markets),
            below_compiler_confidence=self._count_with_pct(below_confidence, max(compiled_count, 1)),
            missing_source_deadline_conditions=self._count_with_pct(missing_fields, max(compiled_count, 1)),
            compiler_abstention_or_error=self._count_with_pct(max(total_markets - compiled_count, 0), total_markets),
        )

    def _build_identity_report(self, total_markets: int) -> CandidateFunnelIdentityReport:
        reviews = self._session.query(IdentityMatchReview).all()
        status_counts = Counter(row.status for row in reviews)
        false_equivalence = sum(
            1
            for row in reviews
            if str((row.review_payload or {}).get("identity_type")) == "false_equivalence"
        )
        reason_counts = Counter(
            reason
            for row in reviews
            for reason in ((row.review_payload or {}).get("review_reasons") or [])
        )
        cluster_rows = (
            self._session.query(EventIdentityCluster)
            .filter(EventIdentityCluster.status == "active")
            .all()
        )
        member_rows = self._session.query(IdentityClusterMember.cluster_id, IdentityClusterMember.raw_market_id).all()
        members_by_cluster: dict[str, set[str]] = {}
        for cluster_id, raw_market_id in member_rows:
            if raw_market_id is None:
                continue
            members_by_cluster.setdefault(str(cluster_id), set()).add(raw_market_id)
        tradeable_clusters = sum(
            1 for cluster in cluster_rows if len(members_by_cluster.get(str(cluster.id), set())) >= 2
        )
        cluster_sizes = [len(members_by_cluster.get(str(cluster.id), set())) for cluster in cluster_rows]
        avg_cluster_size = round(sum(cluster_sizes) / len(cluster_sizes), 2) if cluster_sizes else 0.0
        return CandidateFunnelIdentityReport(
            identity_links=len(reviews),
            verified=self._count_with_pct(status_counts.get("verified", 0), max(total_markets, 1)),
            ambiguous=self._count_with_pct(status_counts.get("ambiguous", 0), max(total_markets, 1)),
            unresolved=self._count_with_pct(status_counts.get("unresolved", 0), max(total_markets, 1)),
            rejected=self._count_with_pct(status_counts.get("rejected", 0), max(total_markets, 1)),
            false_equivalence=self._count_with_pct(false_equivalence, max(total_markets, 1)),
            top_blocking_reasons=self._reason_rows(reason_counts, limit=10),
            cluster_count=len(cluster_rows),
            average_cluster_size=avg_cluster_size,
            clusters_with_tradeable_pairs=tradeable_clusters,
        )

    def _build_relation_report(self, observations: list[ShadowCandidateObservation]) -> CandidateFunnelRelationReport:
        relation_reviews = self._session.query(RelationReview).all()
        logical_relations = self._session.query(LogicalRelation).all()
        logical_sets = self._session.query(LogicalRelationSet).all()
        relation_type_counts = Counter(
            [row.relation_type for row in logical_relations] + [row.relation_type for row in logical_sets]
        )
        semantic_confirmed = sum(
            1 for row in logical_relations if row.created_by == "semantic_relation_analyzer" and row.proof_status == "verified"
        ) + sum(
            1 for row in logical_sets if row.created_by == "semantic_relation_analyzer" and row.proof_status == "verified"
        )
        semantic_veto = sum(
            1
            for row in logical_relations
            if row.created_by == "semantic_relation_analyzer" and not row.tradeable_relation
        ) + sum(
            1
            for row in logical_sets
            if row.created_by == "semantic_relation_analyzer" and not row.tradeable_relation
        )
        semantic_abstention = sum(
            1
            for row in logical_relations
            if (row.evidence or {}).get("abstention_reason")
        ) + sum(
            1
            for row in logical_sets
            if (row.evidence or {}).get("abstention_reason")
        )
        top_blockers = self._reason_rows(
            Counter(
                reason
                for row in relation_reviews
                for reason in [str((row.review_payload or {}).get("abstention_reason") or "").strip()]
                if reason
            ),
            limit=10,
        )
        # Hypothesis generator breakdown: query evidence JSON for source tag
        hypothesis_relations = [
            row for row in logical_relations
            if (row.evidence or {}).get("hypothesis_source") == "hypothesis_generator"
        ]
        frame_relations = [
            row for row in logical_relations
            if (row.evidence or {}).get("hypothesis_source") != "hypothesis_generator"
        ]
        hypotheses_by_type: dict[str, int] = dict(
            Counter(row.relation_type for row in hypothesis_relations)
        )
        tradeable_by_hypothesis = sum(1 for row in hypothesis_relations if row.tradeable_relation)
        tradeable_by_frame = sum(1 for row in frame_relations if row.tradeable_relation)

        return CandidateFunnelRelationReport(
            relation_proposals=len(relation_reviews),
            logical_relations=len(logical_relations),
            logical_relation_sets=len(logical_sets),
            confirmed_semantic=semantic_confirmed,
            semantic_veto=semantic_veto,
            semantic_abstention=semantic_abstention,
            tradeable_true=sum(1 for row in logical_relations if row.tradeable_relation) + sum(
                1 for row in logical_sets if row.tradeable_relation
            ),
            tradeable_false=sum(1 for row in logical_relations if not row.tradeable_relation) + sum(
                1 for row in logical_sets if not row.tradeable_relation
            ),
            relation_types=dict(sorted(relation_type_counts.items())),
            top_blocking_reasons=top_blockers,
            frame_proposals=len(frame_relations),
            hypothesis_proposals=len(hypothesis_relations),
            hypotheses_by_type=hypotheses_by_type,
            tradeable_by_hypothesis=tradeable_by_hypothesis,
            tradeable_by_frame=tradeable_by_frame,
        )

    def _build_solver_report(self, observations: list[ShadowCandidateObservation]) -> CandidateFunnelSolverReport:
        proof_distribution = Counter(
            observation.proof_status for observation in observations if observation.proof_status
        )
        false_arb = Counter(
            observation.false_arbitrage_label
            for observation in observations
            if observation.false_arbitrage_label
        )
        decisions = [
            SolverDecisionEntry(
                relation_key=observation.relation_key,
                relation_kind=observation.relation_kind,
                relation_type=observation.relation_type,
                market_ids=list(observation.market_ids or []),
                identity_status=observation.identity_status,
                solver_called=bool(observation.solver_called),
                solver_skip_reason=observation.solver_skip_reason,
                solver_none_reason=observation.solver_none_reason,
                proof_status=observation.proof_status,
                valid_state_count=observation.valid_state_count,
                impossible_state_count=observation.impossible_state_count,
                displayed_edge=observation.displayed_edge,
                executable_edge=observation.executable_edge,
                worst_case_payoff=observation.worst_case_payoff,
                false_arbitrage_label=observation.false_arbitrage_label,
                min_profit_threshold=observation.min_profit_threshold,
                rejected_by_threshold=bool(observation.rejected_by_threshold),
                rejected_by_identity=bool(observation.rejected_by_identity),
                rejected_by_false_arbitrage=bool(observation.rejected_by_false_arbitrage),
                rejected_by_dedup=bool(observation.rejected_by_dedup),
            )
            for observation in observations
        ]
        return CandidateFunnelSolverReport(
            total_considered=len(observations),
            solver_called=sum(1 for item in observations if item.solver_called),
            solver_not_called=sum(1 for item in observations if not item.solver_called),
            returned_none=sum(1 for item in observations if item.solver_none_reason),
            produced_proof=sum(1 for item in observations if item.displayed_edge is not None),
            proof_status_distribution=dict(sorted(proof_distribution.items())),
            false_arbitrage_labels=dict(sorted((key, value) for key, value in false_arb.items() if key)),
            threshold_rejects=sum(1 for item in observations if item.rejected_by_threshold),
            decisions=decisions,
        )

    @staticmethod
    def _build_persistence_report(observations: list[ShadowCandidateObservation]) -> CandidateFunnelPersistenceReport:
        return CandidateFunnelPersistenceReport(
            solver_results=sum(1 for item in observations if item.displayed_edge is not None),
            above_threshold=sum(
                1
                for item in observations
                if item.displayed_edge is not None and not item.rejected_by_threshold
            ),
            rejected_false_arbitrage=sum(1 for item in observations if item.rejected_by_false_arbitrage),
            duplicate_dedup=sum(1 for item in observations if item.rejected_by_dedup),
            persisted_candidates=sum(1 for item in observations if item.persisted_candidate_id is not None),
            persistence_failures=sum(
                1
                for item in observations
                if item.displayed_edge is not None
                and item.persisted_candidate_id is None
                and not item.rejected_by_threshold
                and not item.rejected_by_false_arbitrage
                and not item.rejected_by_dedup
            ),
        )

    @staticmethod
    def _build_preview_report(observations: list[ShadowCandidateObservation]) -> CandidateFunnelPreviewReport:
        return CandidateFunnelPreviewReport(
            positive_displayed_edge=sum(
                1 for item in observations if item.displayed_edge is not None and item.displayed_edge > 0
            ),
            positive_executable_edge=sum(
                1 for item in observations if item.executable_edge is not None and item.executable_edge > 0
            ),
            failed_only_execution_evidence_missing=sum(
                1 for item in observations if list(item.minimal_relaxation or []) == ["execution_gate_relaxed"]
            ),
            failed_only_identity_unverified=sum(
                1 for item in observations if list(item.minimal_relaxation or []) == ["identity_gate_relaxed"]
            ),
            failed_only_profit_below_threshold=sum(
                1 for item in observations if list(item.minimal_relaxation or []) == ["min_profit_threshold_relaxed"]
            ),
        )

    @staticmethod
    def _count_with_pct(count: int, total: int) -> CountWithPct:
        pct = round((count / total) * 100.0, 2) if total > 0 else None
        return CountWithPct(count=count, pct=pct)

    @staticmethod
    def _reason_rows(counter: Counter[str], *, limit: int) -> list[ReasonCount]:
        return [ReasonCount(reason=reason, count=count) for reason, count in counter.most_common(limit)]

    def _count_threshold(self, observations: list[ShadowCandidateObservation], threshold_bps: int) -> int:
        threshold = threshold_bps / 10_000
        return sum(
            1
            for item in observations
            if item.identity_status == "verified"
            and item.tradeable_relation
            and item.false_arbitrage_label is None
            and not item.rejected_by_dedup
            and (item.displayed_edge or -1.0) > threshold
        )

    def _count_identity(self, observations: list[ShadowCandidateObservation], allowed_statuses: set[str]) -> int:
        count = 0
        for item in observations:
            if item.identity_status not in allowed_statuses:
                continue
            if not item.tradeable_relation or item.false_arbitrage_label is not None or item.rejected_by_dedup:
                continue
            if (item.displayed_edge or -1.0) <= _MIN_PROFIT_AFTER_FRICTION:
                continue
            if item.identity_status != "verified" and not bool((item.relaxation_flags or {}).get("identity_gate_relaxed")):
                continue
            count += 1
        return count

    def _count_semantic_tradeable(self, threshold: float) -> int:
        count = 0
        for row in self._session.query(LogicalRelation).all():
            evidence = row.evidence or {}
            confidence = evidence.get("semantic_confidence", row.confidence)
            if isinstance(confidence, (int, float)) and float(confidence) >= threshold and row.proof_status != "rejected":
                count += 1
        for row in self._session.query(LogicalRelationSet).all():
            evidence = row.evidence or {}
            confidence = evidence.get("semantic_confidence", row.confidence)
            if isinstance(confidence, (int, float)) and float(confidence) >= threshold and row.proof_status != "rejected":
                count += 1
        return count

    def _count_execution_mode(self, observations: list[ShadowCandidateObservation], *, mode: str) -> int:
        count = 0
        for item in observations:
            if item.identity_status != "verified" or not item.tradeable_relation:
                continue
            if item.false_arbitrage_label is not None or item.rejected_by_dedup:
                continue
            if (item.displayed_edge or -1.0) <= _MIN_PROFIT_AFTER_FRICTION:
                continue
            if mode == "block" and item.execution_evidence_missing:
                continue
            count += 1
        return count

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
