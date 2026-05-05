from __future__ import annotations

from sqlalchemy.orm import Session

from parallax.candidates.evidence import (
    load_identity_blocking_reason,
    load_identity_confidence,
    load_identity_provenance,
    load_identity_status,
    load_identity_version,
)
from parallax.config import settings
from parallax.db.models import CompiledContract, CompiledProposition, RawMarket
from parallax.detection.hypothesis_generator import RelationHypothesisGenerator
from parallax.detection.proposal_generator import RelationProposal, RelationProposalGenerator
from parallax.detection.semantic import SemanticRelationAnalyzer
from parallax.detection.semantic_veto import PartitionReviewResult, SemanticVeto
from parallax.event_frames.frame_builder import EventFrameBuilder
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.graph.repository import GraphRepository
from parallax.logic.counterexample_engine import CounterexampleEngine
from parallax.logic.logic_engine import LogicEngine
from parallax.shared.relation_signals import RELATION_EVIDENCE_VERSION, build_relation_signals
from parallax.shared.schemas import (
    CompiledPropositionSchema,
    ContractSchema,
    CounterexampleRecord,
    IdentityResolutionStatus,
    RelationType,
)


class RelationPipelineService:
    _CREATED_BY_LOGIC = "logic_engine"
    _CREATED_BY_SEMANTIC = "semantic_relation_analyzer"
    _PROPOSAL_PRIORITY: dict[RelationType, int] = {
        RelationType.EQUIVALENT: 0,
        RelationType.DUPLICATE: 1,
        RelationType.MUTUALLY_EXCLUSIVE: 2,
        RelationType.EXHAUSTIVE_PARTITION: 3,
        RelationType.SUBSET: 4,
        RelationType.SUPERSET: 4,
        RelationType.INVERSE: 5,
        RelationType.SAME_EVENT_DIFFERENT_SOURCE: 6,
        RelationType.SAME_EVENT_DIFFERENT_ORACLE: 6,
        RelationType.SAME_EVENT_DIFFERENT_DEADLINE: 6,
        RelationType.SAME_EVENT_INDEPENDENT: 7,
        RelationType.RELATED_BUT_NOT_TRADEABLE: 8,
        RelationType.SAME_EVENT_FAMILY: 9,
    }
    _SOURCE_PRIORITY = {
        "hypothesis_generator": 0,
        "frame": 1,
    }

    def __init__(
        self,
        session: Session,
        graph_repo: GraphRepository,
        semantic_analyzer: SemanticRelationAnalyzer | None = None,
        min_semantic_confidence: float | None = None,
    ) -> None:
        self._session = session
        self._graph_repo = graph_repo
        self._proposal_generator = RelationProposalGenerator()
        self._hypothesis_generator = RelationHypothesisGenerator()
        self._frame_builder = EventFrameBuilder(session)
        self._logic_engine = LogicEngine()
        self._semantic = semantic_analyzer
        self._semantic_veto = SemanticVeto(semantic_analyzer) if semantic_analyzer is not None else None
        self._counterexamples = CounterexampleEngine()
        self._min_semantic_confidence = (
            settings.semantic_min_relation_confidence
            if min_semantic_confidence is None
            else min_semantic_confidence
        )

    async def run(self, markets: list[RawMarket]) -> int:
        frame_ids = self._frame_builder.build_for_markets(markets)
        propositions = {
            market.id: proposition
            for market in markets
            for proposition in [self._get_proposition(market.id)]
            if proposition is not None
        }
        frame_proposals = self._proposal_generator.generate(
            markets=markets, propositions=propositions, frame_ids=frame_ids
        )
        hypothesis_proposals = self._hypothesis_generator.generate(
            markets=markets, propositions=propositions, frame_ids=frame_ids
        )
        proposals = self._select_primary_proposals(frame_proposals + hypothesis_proposals)

        added = 0
        for proposal in proposals:
            proposition_a = propositions.get(proposal.from_market_id)
            proposition_b = propositions.get(proposal.to_market_id)
            market_a = self._get_market(proposal.from_market_id)
            market_b = self._get_market(proposal.to_market_id)
            contract_a = self._get_contract(proposal.from_market_id)
            contract_b = self._get_contract(proposal.to_market_id)
            if not all([proposition_a, proposition_b, market_a, market_b, contract_a, contract_b]):
                continue

            decision = self._logic_engine.adjudicate(proposal, proposition_a, proposition_b)
            identity_provenance = load_identity_provenance(
                self._session,
                [proposal.from_market_id, proposal.to_market_id],
            )
            evidence = {
                **proposal.evidence,
                **decision.evidence,
                "evidence_version": RELATION_EVIDENCE_VERSION,
                "is_confirmed": decision.proof_status == "verified",
                "structural_relation_type": proposal.proposed_relation_type.value,
                "proof_status": decision.proof_status,
                "tradeable_relation": decision.tradeable_relation,
                "frame_id": proposal.frame_id,
                "comparison_axes": [],
                "breaking_scenarios": [],
                "relation_signals": build_relation_signals(market_a, market_b, contract_a, contract_b),
                "identity_provenance": identity_provenance,
                "identity_status": load_identity_status(identity_provenance).value,
                "identity_confidence": load_identity_confidence(identity_provenance),
                "identity_version": load_identity_version(identity_provenance),
                "identity_blocking_reason": load_identity_blocking_reason(identity_provenance),
            }

            reviewed_type = decision.relation_type
            confidence = decision.confidence
            created_by = self._CREATED_BY_LOGIC
            classification = None
            if decision.requires_semantic_review and self._semantic_veto is not None:
                classification = await self._semantic_veto.review(
                    contract_a,
                    contract_b,
                    proposed_relation=decision.relation_type,
                    hypothesis_context=proposal.semantic_question,
                )
                if classification is not None:
                    reviewed_type = classification.relation_type
                    confidence = classification.confidence
                    created_by = self._CREATED_BY_SEMANTIC
                    evidence.update(
                        {
                            "is_confirmed": classification.is_confirmed,
                            "semantic_reasoning": classification.reasoning,
                            "semantic_relation_type": classification.relation_type.value,
                            "semantic_confidence": classification.confidence,
                            "comparison_axes": classification.comparison_axes,
                            "breaking_scenarios": [
                                scenario.model_dump() for scenario in classification.breaking_scenarios
                            ],
                            "tradeable_relation": bool(classification.tradeable_relation and classification.is_confirmed),
                            "proof_status": classification.proof_status,
                        }
                    )
                    if (
                        classification.tradeable_relation
                        and classification.is_confirmed
                        and classification.confidence >= self._min_semantic_confidence
                    ):
                        evidence["tradeable_relation"] = True
                        evidence["proof_status"] = "verified"
                    else:
                        evidence["tradeable_relation"] = False
                        if classification.proof_status == "verified":
                            evidence["proof_status"] = "needs_review"
                    if not classification.is_confirmed:
                        evidence["abstention_reason"] = (
                            "semantic analysis found counterexamples or insufficient logical proof"
                        )
            self._apply_identity_gate(evidence)

            relation_type_for_record = reviewed_type
            relation_lookup_type = relation_type_for_record
            if self._graph_repo.relation_exists(
                proposal.from_market_id,
                proposal.to_market_id,
                relation_lookup_type,
            ):
                continue

            review_id: str | None = None
            if isinstance(self._graph_repo, PostgresGraphRepository):
                review_id = self._graph_repo.add_review(
                    from_market_id=proposal.from_market_id,
                    to_market_id=proposal.to_market_id,
                    proposed_relation_type=proposal.proposed_relation_type,
                    reviewed_relation_type=reviewed_type,
                    proof_status=str(evidence.get("proof_status", "verified")),
                    tradeable_relation=bool(evidence.get("tradeable_relation", False)),
                    review_payload=evidence,
                    reviewed_by=created_by,
                )

            relation_id = self._graph_repo.add_relation(
                from_market_id=proposal.from_market_id,
                to_market_id=proposal.to_market_id,
                relation_type=reviewed_type,
                confidence=confidence,
                evidence=evidence,
                created_by=created_by,
            )
            self._persist_counterexamples(
                relation_id=relation_id,
                review_id=review_id,
                relation_type=relation_type_for_record,
                contract_a=contract_a,
                contract_b=contract_b,
                classification=classification,
                created_by=created_by,
            )
            added += 1
        added += await self._persist_partition_sets(markets, propositions, frame_ids)
        return added

    def _select_primary_proposals(self, proposals: list[RelationProposal]) -> list[RelationProposal]:
        selected: dict[tuple[str, str], RelationProposal] = {}
        for proposal in proposals:
            pair_key = tuple(sorted((proposal.from_market_id, proposal.to_market_id)))
            current = selected.get(pair_key)
            if current is None or self._proposal_score(proposal) < self._proposal_score(current):
                selected[pair_key] = proposal
        return list(selected.values())

    def _proposal_score(self, proposal: RelationProposal) -> tuple[int, float, int, str]:
        relation_priority = self._PROPOSAL_PRIORITY.get(proposal.proposed_relation_type, 99)
        source_priority = self._SOURCE_PRIORITY.get(getattr(proposal, "hypothesis_source", "frame"), 50)
        confidence = -float(getattr(proposal, "confidence", 0.0))
        return (relation_priority, confidence, source_priority, proposal.proposed_relation_type.value)

    async def _persist_partition_sets(
        self,
        markets: list[RawMarket],
        propositions: dict[str, CompiledPropositionSchema],
        frame_ids: dict[str, str],
    ) -> int:
        grouped: dict[str, list[CompiledPropositionSchema]] = {}
        for market in markets:
            frame_id = frame_ids.get(market.id)
            proposition = propositions.get(market.id)
            if frame_id is None or proposition is None:
                continue
            grouped.setdefault(frame_id, []).append(proposition)

        added = 0
        for frame_id, members in grouped.items():
            set_decision = self._logic_engine.adjudicate_partition(members)
            if set_decision is None:
                continue
            reviewed_type = set_decision.relation_type
            proof_status = set_decision.proof_status
            tradeable_relation = set_decision.tradeable_relation
            confidence = set_decision.confidence
            created_by = self._CREATED_BY_LOGIC
            set_key = "|".join(sorted(member.raw_market_id for member in members))
            evidence = {
                **set_decision.evidence,
                "frame_id": frame_id,
                "proof_status": proof_status,
                "tradeable_relation": tradeable_relation,
                "set_key": set_key,
                "member_market_ids": sorted(member.raw_market_id for member in members),
                "evidence_version": RELATION_EVIDENCE_VERSION,
                "counterexample_status": "pending",
                "semantic_pair_reviews": [],
            }
            identity_provenance = load_identity_provenance(self._session, evidence["member_market_ids"])
            evidence["identity_provenance"] = identity_provenance
            evidence["identity_status"] = load_identity_status(identity_provenance).value
            evidence["identity_confidence"] = load_identity_confidence(identity_provenance)
            evidence["identity_version"] = load_identity_version(identity_provenance)
            evidence["identity_blocking_reason"] = load_identity_blocking_reason(identity_provenance)
            partition_review: PartitionReviewResult | None = None
            if set_decision.requires_semantic_review and self._semantic_veto is not None:
                contracts = [self._get_contract(member.raw_market_id) for member in members]
                complete_contracts = [contract for contract in contracts if contract is not None]
                if len(complete_contracts) == len(members) and len(complete_contracts) >= 2:
                    partition_review = await self._semantic_veto.review_partition(
                        complete_contracts,
                        member_market_ids=evidence["member_market_ids"],
                        proposed_relation=RelationType.EXHAUSTIVE_PARTITION,
                    )
                    if partition_review is not None:
                        classification = partition_review.classification
                        evidence["semantic_relation_type"] = classification.relation_type.value
                        evidence["semantic_confidence"] = classification.confidence
                        evidence["comparison_axes"] = classification.comparison_axes
                        evidence["breaking_scenarios"] = [item.model_dump() for item in classification.breaking_scenarios]
                        evidence["semantic_pair_reviews"] = partition_review.pair_reviews
                        proof_status = classification.proof_status
                        tradeable_relation = bool(classification.tradeable_relation and classification.is_confirmed)
                        evidence["proof_status"] = proof_status
                        evidence["tradeable_relation"] = tradeable_relation
                        if not classification.is_confirmed:
                            evidence["abstention_reason"] = (
                                "semantic veto blocked exhaustive partition tradeability"
                            )
                        created_by = self._CREATED_BY_SEMANTIC
            self._apply_identity_gate(evidence)

            contracts_for_counterexamples = [
                self._get_contract(member.raw_market_id)
                for member in members
            ]
            complete_contracts = [contract for contract in contracts_for_counterexamples if contract is not None]
            partition_counterexamples = self._counterexamples.collect_partition(
                contracts=complete_contracts,
                pair_reviews=evidence.get("semantic_pair_reviews"),
            ) if len(complete_contracts) == len(members) else []
            evidence["counterexample_status"] = "recorded" if partition_counterexamples else "none_found"
            self._graph_repo.add_relation_set(
                set_key=set_key,
                member_market_ids=evidence["member_market_ids"],
                relation_type=reviewed_type,
                confidence=confidence,
                evidence=evidence,
                created_by=created_by,
            )

            pair_ids = [member.raw_market_id for member in members]
            for index, from_market_id in enumerate(pair_ids):
                for to_market_id in pair_ids[index + 1 :]:
                    if self._graph_repo.relation_exists(from_market_id, to_market_id, reviewed_type):
                        continue
                    review_id: str | None = None
                    if isinstance(self._graph_repo, PostgresGraphRepository):
                        review_id = self._graph_repo.add_review(
                            from_market_id=from_market_id,
                            to_market_id=to_market_id,
                            proposed_relation_type=RelationType.EXHAUSTIVE_PARTITION,
                            reviewed_relation_type=reviewed_type,
                            proof_status=proof_status,
                            tradeable_relation=tradeable_relation,
                            review_payload=evidence,
                            reviewed_by=created_by,
                        )
                    relation_id = self._graph_repo.add_relation(
                        from_market_id=from_market_id,
                        to_market_id=to_market_id,
                        relation_type=reviewed_type,
                        confidence=confidence,
                        evidence=evidence,
                        created_by=created_by,
                    )
                    if partition_counterexamples:
                        for scenario in partition_counterexamples:
                            self._graph_repo.add_counterexample_record(
                                CounterexampleRecord(
                                    relation_id=relation_id,
                                    review_id=review_id,
                                    relation_type=reviewed_type,
                                    set_key=set_key,
                                    scenario_description=scenario.scenario_description,
                                    resolution_a=scenario.resolution_a,
                                    resolution_b=scenario.resolution_b,
                                    why_different=scenario.why_different,
                                    source=created_by,
                                    created_by=created_by,
                                    metadata={"frame_id": frame_id, "member_market_ids": evidence["member_market_ids"]},
                                )
                            )
                    else:
                        self._graph_repo.add_counterexample_record(
                            CounterexampleRecord(
                                relation_id=relation_id,
                                review_id=review_id,
                                relation_type=reviewed_type,
                                set_key=set_key,
                                scenario_description="No counterexample found for exhaustive partition review.",
                                resolution_a="AMBIGUOUS",
                                resolution_b="AMBIGUOUS",
                                why_different="full-set semantic and structural review found no breaking scenario",
                                source=created_by,
                                status="none_found",
                                created_by=created_by,
                                metadata={"frame_id": frame_id, "member_market_ids": evidence["member_market_ids"]},
                            )
                        )
                    added += 1
        return added

    @staticmethod
    def _apply_identity_gate(evidence: dict[str, object]) -> None:
        identity_status = IdentityResolutionStatus(str(evidence.get("identity_status", "unresolved")))
        if identity_status == IdentityResolutionStatus.VERIFIED:
            return
        evidence["tradeable_relation"] = False
        if str(evidence.get("proof_status", "verified")) == "verified":
            evidence["proof_status"] = "needs_review"
        reason = evidence.get("identity_blocking_reason") or f"identity status is {identity_status.value}"
        abstention = str(evidence.get("abstention_reason") or "")
        if abstention:
            evidence["abstention_reason"] = f"{abstention}; {reason}"
        else:
            evidence["abstention_reason"] = reason

    def _persist_counterexamples(
        self,
        *,
        relation_id: str,
        review_id: str | None,
        relation_type: RelationType,
        contract_a: ContractSchema,
        contract_b: ContractSchema,
        classification,
        created_by: str,
    ) -> None:
        records = self._counterexamples.collect(
            relation_type=relation_type,
            contract_a=contract_a,
            contract_b=contract_b,
            classification=classification,
        )
        relation_ref = relation_id if isinstance(relation_id, str) else None
        review_ref = review_id if isinstance(review_id, str) else None
        if not records:
            self._graph_repo.add_counterexample_record(
                CounterexampleRecord(
                    relation_id=relation_ref,
                    review_id=review_ref,
                    relation_type=relation_type,
                    scenario_description="No counterexample found for required proof types.",
                    resolution_a="AMBIGUOUS",
                    resolution_b="AMBIGUOUS",
                    why_different="no blocking scenario identified during current proof pass",
                    source=created_by,
                    status="none_found",
                    created_by=created_by,
                )
            )
            return

        for counterexample in records:
            self._graph_repo.add_counterexample_record(
                CounterexampleRecord(
                    relation_id=relation_ref,
                    review_id=review_ref,
                    relation_type=relation_type,
                    scenario_description=counterexample.scenario_description,
                    resolution_a=counterexample.resolution_a,
                    resolution_b=counterexample.resolution_b,
                    why_different=counterexample.why_different,
                    source=created_by,
                    created_by=created_by,
                )
            )

    def _get_contract(self, market_id: str) -> ContractSchema | None:
        row = (
            self._session.query(CompiledContract)
            .filter_by(raw_market_id=market_id)
            .order_by(CompiledContract.compiled_at.desc())
            .first()
        )
        return ContractSchema.model_validate(row.contract_json) if row else None

    def _get_proposition(self, market_id: str) -> CompiledPropositionSchema | None:
        row = (
            self._session.query(CompiledProposition)
            .filter(CompiledProposition.raw_market_id == market_id)
            .order_by(CompiledProposition.compiled_at.desc())
            .first()
        )
        return CompiledPropositionSchema.model_validate(row.proposition_json) if row else None

    def _get_market(self, market_id: str) -> RawMarket | None:
        return self._session.get(RawMarket, market_id)


ProverService = RelationPipelineService
RelationAnalysisService = RelationPipelineService
