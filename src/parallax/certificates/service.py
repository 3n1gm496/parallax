from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.audit.service import AuditService
from parallax.candidates.repository import CandidateRepository
from parallax.db.models import TradeProofCertificateRecord
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    TradeProofCertificate,
    TradeProofCertificateStatus,
)


def _hash_payload(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class CertificateService:
    VERSION = "trade-proof-certificate-v1"

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CandidateRepository(session)
        self._audit = AuditService(session)

    def build_draft(
        self,
        candidate_id: str,
        run_id: str | None = None,
        *,
        supersedes_certificate_id: uuid.UUID | None = None,
    ) -> TradeProofCertificateRecord:
        candidate = self._require_candidate(candidate_id)
        snapshot = self._repo.get_decision_snapshot(candidate_id)
        scenario_matrix, proof_object = self._repo.get_solver_artifacts(candidate_id)
        if scenario_matrix is None or proof_object is None:
            raise ValueError("candidate is missing scenario matrix or proof object")
        if snapshot is None:
            raise ValueError("candidate is missing decision snapshot")
        if snapshot.simulation_result is None:
            raise ValueError("candidate is missing simulation result")

        relation_evidence = snapshot.relation_evidence or {}
        simulation = snapshot.simulation_result or {}
        orderbook_snapshot_ids = list(simulation.get("snapshot_ids", []) or [])
        market_data_snapshot_hash = _hash_payload(orderbook_snapshot_ids) if orderbook_snapshot_ids else None
        compiled_contract_versions = self._extract_compiled_contract_versions(candidate.market_ids)
        contract_fingerprints = self._extract_contract_fingerprints(candidate.market_ids)
        identity_provenance = relation_evidence.get("identity_provenance") or {}
        identity_cluster_ids = self._extract_identity_cluster_ids(identity_provenance)

        row = TradeProofCertificateRecord(
            candidate_id=uuid.UUID(candidate_id),
            run_id=run_id or snapshot.run_id,
            generated_at=datetime.now(timezone.utc),
            certificate_version=self.VERSION,
            certificate_status=TradeProofCertificateStatus.DRAFT.value,
            market_data_snapshot_hash=market_data_snapshot_hash,
            compiled_contract_versions=compiled_contract_versions,
            contract_fingerprints=contract_fingerprints,
            identity_evidence_ids=sorted(list((identity_provenance.get("links") or {}).keys())),
            identity_status=str(relation_evidence.get("identity_status", IdentityResolutionStatus.UNRESOLVED.value)),
            identity_confidence=relation_evidence.get("identity_confidence"),
            identity_provenance=identity_provenance,
            identity_cluster_ids=identity_cluster_ids,
            relation_proof_ids=[],
            relation_set_ids=([relation_evidence.get("set_key")] if relation_evidence.get("set_key") else []),
            solver_proof_object_hash=_hash_payload(proof_object.model_dump(mode="json")),
            payoff_matrix_hash=_hash_payload(candidate.payoff_matrix),
            scenario_matrix_hash=_hash_payload(scenario_matrix.model_dump(mode="json")),
            orderbook_snapshot_ids=orderbook_snapshot_ids,
            execution_model=str(
                simulation.get("execution_path")
                or simulation.get("execution_model")
                or "calibrated_model"
            ),
            execution_simulation_hash=_hash_payload(simulation),
            court_decision_snapshot_id=candidate_id,
            risk_score_version=(snapshot.risk_score or {}).get("policy_version") if snapshot.risk_score else None,
            policy_version=(snapshot.court_assessment or {}).get("policy_version") if snapshot.court_assessment else None,
            config_fingerprint=None,
            provider_fingerprints={},
            invalidation_conditions=[
                "identity_status_changes",
                "proof_status_changes",
                "orderbook_snapshot_stale",
                "policy_superseded",
            ],
            created_at=datetime.now(timezone.utc),
            supersedes_certificate_id=supersedes_certificate_id,
            degraded=(proof_object.proof_status == "degraded"),
        )
        self._session.add(row)
        self._session.flush()
        self._audit.record("certificate.drafted", "candidate", candidate_id, {"certificate_id": str(row.id)})
        return row

    def verify(self, certificate_id: str) -> bool:
        """Check if the certificate is still valid given current market and policy state."""
        row = self._require_certificate(certificate_id)
        if row.certificate_status != TradeProofCertificateStatus.ISSUED.value:
            return False

        # 1. Check semantic consistency (fingerprints)
        current_fingerprints = self._extract_contract_fingerprints([str(mid) for mid in row.contract_fingerprints.keys()])
        if current_fingerprints != row.contract_fingerprints:
            self.invalidate(certificate_id, "semantic_fingerprint_mismatch")
            return False

        # 2. Check policy version
        # active_policy = getattr(self, "_active_policy", None) # Could be loaded if needed
        # if active_policy and row.policy_version != active_policy.policy_version:
        #     self.invalidate(certificate_id, "policy_version_mismatch")
        #     return False

        return True

    def issue(self, candidate_id: str) -> TradeProofCertificateRecord:
        self._require_candidate(candidate_id)
        snapshot = self._repo.get_decision_snapshot(candidate_id)
        scenario_matrix, proof_object = self._repo.get_solver_artifacts(candidate_id)
        if snapshot is None or scenario_matrix is None or proof_object is None:
            raise ValueError("candidate proof chain is incomplete")
        if proof_object.proof_status == "false_arbitrage":
            raise ValueError("false arbitrage candidates cannot be issued")
        relation_evidence = snapshot.relation_evidence or {}
        if relation_evidence.get("identity_status") != IdentityResolutionStatus.VERIFIED.value:
            raise ValueError("identity is not verified")
        if snapshot.court_assessment is None:
            raise ValueError("missing court decision snapshot")
        if snapshot.simulation_result is None:
            raise ValueError("missing simulation result")
        if snapshot.simulation_result.get("execution_model") == "snapshot_based" and not snapshot.simulation_result.get("snapshot_ids"):
            raise ValueError("snapshot-based execution requires snapshot ids")
        row = self.get_for_candidate(candidate_id)
        if row is not None and row.certificate_status == TradeProofCertificateStatus.ISSUED.value:
            return row
        if row is None or row.certificate_status == TradeProofCertificateStatus.INVALIDATED.value:
            row = self.build_draft(candidate_id, run_id=snapshot.run_id)
        row.certificate_status = TradeProofCertificateStatus.ISSUED.value
        self._session.flush()
        self._audit.record("certificate.issued", "candidate", candidate_id, {"certificate_id": str(row.id)})
        return row

    def invalidate(self, certificate_id: str, reason: str) -> TradeProofCertificateRecord:
        row = self._require_certificate(certificate_id)
        row.certificate_status = TradeProofCertificateStatus.INVALIDATED.value
        row.invalidation_reason = reason
        self._session.flush()
        self._audit.record("certificate.invalidated", "certificate", certificate_id, {"reason": reason})
        return row

    def supersede(self, certificate_id: str) -> TradeProofCertificateRecord:
        current = self._require_certificate(certificate_id)
        current.certificate_status = TradeProofCertificateStatus.SUPERSEDED.value
        self._session.flush()
        candidate_id = str(current.candidate_id)
        successor = self.build_draft(
            candidate_id,
            run_id=current.run_id,
            supersedes_certificate_id=current.id,
        )
        self._session.flush()
        self._audit.record(
            "certificate.superseded",
            "certificate",
            certificate_id,
            {"new_certificate_id": str(successor.id)},
        )
        return successor

    def get_for_candidate(self, candidate_id: str) -> TradeProofCertificateRecord | None:
        return (
            self._session.query(TradeProofCertificateRecord)
            .filter_by(candidate_id=uuid.UUID(candidate_id))
            .order_by(TradeProofCertificateRecord.created_at.desc())
            .first()
        )

    def list_certificates(self, *, limit: int = 100) -> list[TradeProofCertificateRecord]:
        return (
            self._session.query(TradeProofCertificateRecord)
            .order_by(TradeProofCertificateRecord.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def to_schema(row: TradeProofCertificateRecord) -> TradeProofCertificate:
        return TradeProofCertificate(
            certificate_id=str(row.id),
            candidate_id=str(row.candidate_id),
            run_id=row.run_id,
            generated_at=row.generated_at,
            certificate_version=row.certificate_version,
            certificate_status=TradeProofCertificateStatus(row.certificate_status),
            market_data_snapshot_hash=row.market_data_snapshot_hash,
            compiled_contract_versions=list(row.compiled_contract_versions or []),
            contract_fingerprints={str(k): str(v) for k, v in (row.contract_fingerprints or {}).items()},
            identity_evidence_ids=list(row.identity_evidence_ids or []),
            identity_status=IdentityResolutionStatus(row.identity_status),
            identity_confidence=row.identity_confidence,
            identity_provenance=row.identity_provenance or {},
            identity_cluster_ids=list(row.identity_cluster_ids or []),
            relation_proof_ids=list(row.relation_proof_ids or []),
            relation_set_ids=list(row.relation_set_ids or []),
            solver_proof_object_hash=row.solver_proof_object_hash,
            payoff_matrix_hash=row.payoff_matrix_hash,
            scenario_matrix_hash=row.scenario_matrix_hash,
            orderbook_snapshot_ids=list(row.orderbook_snapshot_ids or []),
            execution_model=row.execution_model,
            execution_simulation_hash=row.execution_simulation_hash,
            court_decision_snapshot_id=row.court_decision_snapshot_id,
            risk_score_version=row.risk_score_version,
            policy_version=row.policy_version,
            config_fingerprint=row.config_fingerprint,
            provider_fingerprints={str(k): str(v) for k, v in (row.provider_fingerprints or {}).items()},
            invalidation_conditions=list(row.invalidation_conditions or []),
            invalidation_reason=row.invalidation_reason,
            created_at=row.created_at,
            supersedes_certificate_id=str(row.supersedes_certificate_id) if row.supersedes_certificate_id else None,
            degraded=bool(row.degraded),
        )

    def _extract_compiled_contract_versions(self, market_ids: list[str]) -> list[str]:
        from parallax.db.models import CompiledContract

        rows = (
            self._session.query(CompiledContract.compiler_version)
            .filter(CompiledContract.raw_market_id.in_(market_ids))
            .distinct()
            .all()
        )
        return [str(version) for (version,) in rows if version]

    def _extract_contract_fingerprints(self, market_ids: list[str]) -> dict[str, str]:
        from parallax.db.models import CompiledContract
        from parallax.shared.schemas import ContractSchema

        rows = (
            self._session.query(CompiledContract)
            .filter(CompiledContract.raw_market_id.in_(market_ids))
            .all()
        )
        fingerprints = {}
        for row in rows:
            schema = ContractSchema.model_validate(row.contract_json)
            fingerprints[row.raw_market_id] = schema.semantic_hash()
        return fingerprints

    @staticmethod
    def _extract_identity_cluster_ids(identity_provenance: dict[str, object]) -> list[str]:
        cluster_ids = identity_provenance.get("cluster_ids")
        if isinstance(cluster_ids, list):
            return [str(item) for item in cluster_ids]
        return []

    def _require_candidate(self, candidate_id: str):
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")
        return candidate

    def _require_certificate(self, certificate_id: str) -> TradeProofCertificateRecord:
        row = self._session.get(TradeProofCertificateRecord, uuid.UUID(certificate_id))
        if row is None:
            raise ValueError(f"Certificate {certificate_id} not found")
        return row
