from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.db.models import (
    CandidateDecisionSnapshot,
    DecisionLedgerRecord,
    OpportunityCandidate,
    SolverAuditRecordModel,
)
from parallax.shared.schemas import (
    CourtAssessment,
    CourtDecision,
    DecisionSnapshot,
    DecisionLedgerEntry,
    OutcomeStateSpace,
    OpportunityType,
    PayoffMatrix,
    ProofObject,
    RelationEvidenceResponse,
    RiskScore,
    SolverAuditRecord,
    SimulationResult,
)


class CandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        market_ids: list[str],
        payoff_matrix: PayoffMatrix,
        opportunity_type: OpportunityType,
        risk_scores: dict,
        *,
        scenario_matrix: OutcomeStateSpace,
        proof_object: ProofObject,
        solver_version: str,
        constraint_fingerprint: str,
        basket: dict[str, object] | None = None,
        false_arbitrage_label: str | None = None,
        audit_record: SolverAuditRecord | None = None,
    ) -> OpportunityCandidate:
        scenario_payload = scenario_matrix.model_dump(mode="json")
        proof_payload = proof_object.model_dump(mode="json")
        if not scenario_payload or not proof_payload:
            raise ValueError("scenario_matrix and proof_object are required for candidate persistence")
        candidate = OpportunityCandidate(
            id=uuid.uuid4(),
            market_ids=market_ids,
            payoff_matrix=payoff_matrix.model_dump(),
            scenario_matrix_json=scenario_payload,
            proof_object_json=proof_payload,
            solver_version=solver_version,
            constraint_fingerprint=constraint_fingerprint,
            basket_json=basket or {},
            false_arbitrage_label=false_arbitrage_label,
            opportunity_type=opportunity_type.value,
            worst_case_payoff=payoff_matrix.worst_case_payoff,
            friction_bps=payoff_matrix.friction_bps,
            risk_scores=risk_scores,
            court_decision=CourtDecision.PENDING.value,
        )
        self._session.add(candidate)
        self._session.flush()
        if audit_record is not None:
            self._session.add(
                SolverAuditRecordModel(
                    candidate_id=candidate.id,
                    constraint_fingerprint=audit_record.constraint_fingerprint,
                    solver_version=audit_record.solver_version,
                    policy_key=audit_record.policy_key,
                    status=audit_record.status,
                    audit_json=audit_record.trace,
                )
            )
            self._session.flush()
        return candidate

    def get(self, candidate_id: str) -> OpportunityCandidate | None:
        return self._session.get(OpportunityCandidate, uuid.UUID(candidate_id))

    def candidate_exists(
        self,
        market_ids: list[str],
        opportunity_type: OpportunityType,
        *,
        constraint_fingerprint: str | None = None,
        solver_version: str | None = None,
    ) -> bool:
        if constraint_fingerprint and solver_version:
            return (
                self._session.query(OpportunityCandidate)
                .filter_by(
                    opportunity_type=opportunity_type.value,
                    status="open",
                    constraint_fingerprint=constraint_fingerprint,
                    solver_version=solver_version,
                )
                .first()
            ) is not None
        target = frozenset(market_ids)
        rows = (
            self._session.query(OpportunityCandidate)
            .filter_by(opportunity_type=opportunity_type.value, status="open")
            .all()
        )
        return any(frozenset(row.market_ids) == target for row in rows)

    def get_solver_artifacts(self, candidate_id: str) -> tuple[OutcomeStateSpace | None, ProofObject | None]:
        candidate = self.get(candidate_id)
        if candidate is None:
            return None, None
        scenario = (
            OutcomeStateSpace.model_validate(candidate.scenario_matrix_json)
            if candidate.scenario_matrix_json
            else None
        )
        proof = ProofObject.model_validate(candidate.proof_object_json) if candidate.proof_object_json else None
        return scenario, proof

    def list_open(self, limit: int = 100, offset: int = 0) -> list[OpportunityCandidate]:
        return (
            self._session.query(OpportunityCandidate)
            .filter_by(status="open")
            .order_by(OpportunityCandidate.detected_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def update_decision(self, candidate_id: str, decision: CourtDecision) -> bool:
        candidate = self.get(candidate_id)
        if candidate is None:
            return False
        candidate.court_decision = decision.value
        self._session.flush()
        return True

    def close(self, candidate_id: str) -> bool:
        candidate = self.get(candidate_id)
        if candidate is None:
            return False
        candidate.status = "closed"
        candidate.resolved_at = datetime.now(timezone.utc)
        self._session.flush()
        return True

    def get_decision_snapshot(self, candidate_id: str) -> CandidateDecisionSnapshot | None:
        return self._session.get(CandidateDecisionSnapshot, uuid.UUID(candidate_id))

    def upsert_decision_snapshot(
        self,
        candidate_id: str,
        *,
        run_id: str | None,
        risk_score: RiskScore | None,
        relation_evidence: RelationEvidenceResponse | None,
        simulation_result: SimulationResult | None,
        court_assessment: CourtAssessment | None,
        decision_ledger_entry: DecisionLedgerEntry | None = None,
        evaluated_at: datetime | None = None,
        snapshot_version: str = "decision-snapshot-v1",
    ) -> CandidateDecisionSnapshot:
        snapshot = self.get_decision_snapshot(candidate_id)
        if snapshot is None:
            snapshot = CandidateDecisionSnapshot(candidate_id=uuid.UUID(candidate_id))
            self._session.add(snapshot)
        snapshot.run_id = run_id
        snapshot.risk_score = risk_score.model_dump() if risk_score is not None else None
        snapshot.relation_evidence = relation_evidence.model_dump() if relation_evidence is not None else None
        snapshot.simulation_result = simulation_result.model_dump() if simulation_result is not None else None
        snapshot.court_assessment = court_assessment.model_dump() if court_assessment is not None else None
        if decision_ledger_entry is not None:
            payload = decision_ledger_entry.model_dump(mode="json")
        else:
            payload = None
        snapshot.decision_ledger_entry = payload
        snapshot.snapshot_version = snapshot_version
        snapshot.evaluated_at = evaluated_at or datetime.now(timezone.utc)
        self._session.flush()
        return snapshot

    def append_decision_ledger_entry(
        self,
        candidate_id: str,
        *,
        run_id: str | None,
        decision_ledger_entry: DecisionLedgerEntry,
    ) -> DecisionLedgerRecord:
        row = DecisionLedgerRecord(
            candidate_id=uuid.UUID(candidate_id),
            run_id=run_id,
            evaluated_at=decision_ledger_entry.evaluated_at,
            decision=decision_ledger_entry.decision.value,
            source_of_truth=decision_ledger_entry.source_of_truth,
            fallback_status=decision_ledger_entry.fallback_status,
            model_version=decision_ledger_entry.model_version,
            confidence=decision_ledger_entry.confidence,
            score=decision_ledger_entry.score,
            input_packet=decision_ledger_entry.input_packet.model_dump(mode="json")
            if decision_ledger_entry.input_packet is not None
            else None,
            relation_proof=decision_ledger_entry.relation_proof.model_dump(mode="json")
            if decision_ledger_entry.relation_proof is not None
            else None,
            execution_evidence=decision_ledger_entry.execution_evidence.model_dump(mode="json")
            if decision_ledger_entry.execution_evidence is not None
            else None,
            blocking_reason=decision_ledger_entry.blocking_reason,
            counterexamples=[item.model_dump(mode="json") for item in decision_ledger_entry.counterexamples],
            metadata_json=decision_ledger_entry.metadata,
        )
        self._session.add(row)
        self._session.flush()
        return row

    @staticmethod
    def snapshot_to_schema(row: CandidateDecisionSnapshot | None) -> DecisionSnapshot | None:
        if row is None:
            return None
        ledger_payload = getattr(row, "decision_ledger_entry", None)
        if hasattr(ledger_payload, "model_dump"):
            ledger_payload = ledger_payload.model_dump(mode="json")
        return DecisionSnapshot(
            candidate_id=str(row.candidate_id),
            run_id=row.run_id,
            risk_score=RiskScore.model_validate(row.risk_score) if row.risk_score else None,
            relation_evidence=RelationEvidenceResponse.model_validate(row.relation_evidence)
            if row.relation_evidence
            else None,
            simulation_result=SimulationResult.model_validate(row.simulation_result)
            if row.simulation_result
            else None,
            court_assessment=CourtAssessment.model_validate(row.court_assessment)
            if row.court_assessment
            else None,
            decision_ledger_entry=DecisionLedgerEntry.model_validate(ledger_payload)
            if isinstance(ledger_payload, dict)
            else None,
            snapshot_version=row.snapshot_version,
            evaluated_at=row.evaluated_at,
        )

    def list_decision_ledger_entries(self, candidate_id: str, *, limit: int = 100) -> list[DecisionLedgerEntry]:
        rows = (
            self._session.query(DecisionLedgerRecord)
            .filter_by(candidate_id=uuid.UUID(candidate_id))
            .order_by(DecisionLedgerRecord.evaluated_at.desc(), DecisionLedgerRecord.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._decision_ledger_to_schema(row) for row in rows]

    @staticmethod
    def _decision_ledger_to_schema(row: DecisionLedgerRecord) -> DecisionLedgerEntry:
        from parallax.shared.schemas import (
            CourtDecision,
            Counterexample,
            DecisionLedgerEntry,
            EvidencePacket,
            ExecutionEvidence,
            RelationProof,
        )

        return DecisionLedgerEntry(
            candidate_id=str(row.candidate_id),
            run_id=row.run_id,
            evaluated_at=row.evaluated_at,
            decision=CourtDecision(row.decision),
            source_of_truth=row.source_of_truth,
            fallback_status=row.fallback_status,
            model_version=row.model_version,
            confidence=row.confidence,
            score=row.score,
            input_packet=EvidencePacket.model_validate(row.input_packet) if row.input_packet else None,
            relation_proof=RelationProof.model_validate(row.relation_proof) if row.relation_proof else None,
            execution_evidence=ExecutionEvidence.model_validate(row.execution_evidence)
            if row.execution_evidence
            else None,
            blocking_reason=row.blocking_reason,
            counterexamples=[Counterexample.model_validate(item) for item in (row.counterexamples or [])],
            metadata=row.metadata_json or {},
        )
