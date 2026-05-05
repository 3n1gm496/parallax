from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.audit.service import AuditService
from parallax.db.models import (
    ActivePolicyVersionRecord,
    AutopsyRecord,
    CalibrationRunRecord,
    CandidateDecisionSnapshot,
    ExecutionFeedbackEventRecord,
    IdentityFeedbackEventRecord,
    OracleFeedbackEventRecord,
    OpportunityCandidate,
    OpportunityTypeScorecardRecord,
    PaperPosition,
    SolverFeedbackEventRecord,
    StrategyKillListRecord,
    TradeProofCertificateRecord,
)
from parallax.shared.schemas import ActivePolicyVersionReport, CalibrationRunReport


@dataclass(slots=True)
class CalibrationResult:
    run: CalibrationRunRecord
    active_policy: ActivePolicyVersionRecord | None


class CalibrationService:
    MIN_SAMPLE_SIZE = 3

    def __init__(self, session: Session) -> None:
        self._session = session
        self._audit = AuditService(session)

    def run(self, *, window_start: datetime | None = None, window_end: datetime | None = None) -> CalibrationResult:
        positions_query = self._session.query(PaperPosition).filter(PaperPosition.status == "CLOSED")
        if window_start is not None:
            positions_query = positions_query.filter(PaperPosition.closed_at >= window_start)
        if window_end is not None:
            positions_query = positions_query.filter(PaperPosition.closed_at <= window_end)
        positions = positions_query.all()
        candidate_ids = [position.candidate_id for position in positions]
        candidates = {
            candidate.id: candidate
            for candidate in self._session.query(OpportunityCandidate)
            .filter(OpportunityCandidate.id.in_(candidate_ids))
            .all()
        }
        snapshots = {
            snapshot.candidate_id: snapshot
            for snapshot in self._session.query(CandidateDecisionSnapshot)
            .filter(CandidateDecisionSnapshot.candidate_id.in_(candidate_ids))
            .all()
        }
        autopsies = (
            self._session.query(AutopsyRecord)
            .filter(AutopsyRecord.candidate_id.in_(candidate_ids))
            .all()
        )
        certificates = {
            row.candidate_id: row
            for row in self._session.query(TradeProofCertificateRecord)
            .filter(TradeProofCertificateRecord.candidate_id.in_(candidate_ids))
            .all()
        }
        autopsies_by_candidate: dict[uuid.UUID, list[AutopsyRecord]] = defaultdict(list)
        for autopsy in autopsies:
            autopsies_by_candidate[autopsy.candidate_id].append(autopsy)

        sample_size = len(positions)
        metrics = self._compute_metrics(positions, candidates, snapshots, autopsies_by_candidate, certificates)
        status = "insufficient_data" if sample_size < self.MIN_SAMPLE_SIZE else "completed"
        policy = None
        if status == "completed":
            policy = self._create_active_policy(metrics, sample_size, window_start, window_end)

        run = CalibrationRunRecord(
            status=status,
            input_window_start=window_start,
            input_window_end=window_end,
            sample_size=sample_size,
            metrics_json=metrics,
            activated_policy_version=policy.policy_version if policy is not None else None,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(run)
        self._session.flush()
        self._persist_scorecards(run.id, metrics.get("opportunity_type_performance", {}))
        self._persist_feedback(run.id, autopsies_by_candidate, positions, candidates)
        self._audit.record(
            "calibration.run.completed",
            "calibration",
            str(run.id),
            {"status": status, "sample_size": sample_size, "activated_policy_version": run.activated_policy_version},
        )
        return CalibrationResult(run=run, active_policy=policy)

    def latest_run(self) -> CalibrationRunRecord | None:
        return self._session.query(CalibrationRunRecord).order_by(CalibrationRunRecord.created_at.desc()).first()

    def active_policy(self) -> ActivePolicyVersionRecord | None:
        row = (
            self._session.query(ActivePolicyVersionRecord)
            .filter(ActivePolicyVersionRecord.status == "active")
            .order_by(ActivePolicyVersionRecord.created_at.desc())
            .first()
        )
        if row is None or not isinstance(getattr(row, "policy_version", None), str):
            return None
        if not isinstance(getattr(row, "court_thresholds", {}), dict):
            return None
        return row

    def list_scorecards(self) -> list[OpportunityTypeScorecardRecord]:
        return (
            self._session.query(OpportunityTypeScorecardRecord)
            .order_by(OpportunityTypeScorecardRecord.created_at.desc())
            .all()
        )

    def list_strategy_kill_list(self) -> list[StrategyKillListRecord]:
        return (
            self._session.query(StrategyKillListRecord)
            .order_by(StrategyKillListRecord.created_at.desc())
            .all()
        )

    @staticmethod
    def run_to_schema(row: CalibrationRunRecord) -> CalibrationRunReport:
        payload = row.metrics_json or {}
        return CalibrationRunReport(
            calibration_run_id=str(row.id),
            status=row.status,
            sample_size=row.sample_size,
            input_window_start=row.input_window_start,
            input_window_end=row.input_window_end,
            generated_at=row.created_at,
            active_policy_version=row.activated_policy_version,
            edge_capture=payload.get("edge_capture"),
            win_rate=payload.get("win_rate"),
            false_positive_rate=payload.get("false_positive_rate"),
            identity_failure_rate=payload.get("identity_failure_rate"),
            execution_miss_rate=payload.get("execution_miss_rate"),
            oracle_divergence_rate=payload.get("oracle_divergence_rate"),
            opportunity_type_performance=payload.get("opportunity_type_performance", {}),
        )

    @staticmethod
    def policy_to_schema(row: ActivePolicyVersionRecord) -> ActivePolicyVersionReport:
        return ActivePolicyVersionReport(
            policy_version=row.policy_version,
            status=row.status,
            provenance=row.provenance or {},
            court_thresholds=row.court_thresholds or {},
            risk_weights=row.risk_weights or {},
            solver_penalties=row.solver_penalties or {},
            execution_calibration=row.execution_calibration or {},
            created_at=row.created_at,
        )

    def _compute_metrics(self, positions, candidates, snapshots, autopsies_by_candidate, certificates) -> dict[str, object]:
        expected_edges: list[float] = []
        actual_pnls: list[float] = []
        profitable = 0
        false_positives = 0
        identity_failures = 0
        execution_misses = 0
        oracle_divergences = 0
        by_type_expected: dict[str, list[float]] = defaultdict(list)
        by_type_realized: dict[str, list[float]] = defaultdict(list)

        for position in positions:
            candidate = candidates.get(position.candidate_id)
            if candidate is None:
                continue
            expected = float(candidate.worst_case_payoff)
            realized = float(position.actual_pnl or 0.0)
            expected_edges.append(expected)
            actual_pnls.append(realized)
            if realized > 0:
                profitable += 1
            else:
                false_positives += 1
            by_type_expected[candidate.opportunity_type].append(expected)
            by_type_realized[candidate.opportunity_type].append(realized)
            for autopsy in autopsies_by_candidate.get(position.candidate_id, []):
                labels = set(autopsy.labels or [])
                if autopsy.identity_error or "false_equivalence" in labels:
                    identity_failures += 1
                if "execution_miss" in labels or "stale_quote_miss" in labels:
                    execution_misses += 1
                if autopsy.resolution_type == "ORACLE_DIVERGENCE" or "oracle_mismatch" in labels:
                    oracle_divergences += 1

        sample = len(expected_edges)
        edge_capture = sum(actual_pnls) / sum(expected_edges) if sample and sum(expected_edges) else None
        opportunity_type_performance = {
            key: round(sum(by_type_realized[key]) / max(len(by_type_realized[key]), 1), 4)
            for key in by_type_realized
        }
        return {
            "edge_capture": round(edge_capture, 4) if edge_capture is not None else None,
            "win_rate": round(profitable / max(sample, 1), 4) if sample else None,
            "false_positive_rate": round(false_positives / max(sample, 1), 4) if sample else None,
            "identity_failure_rate": round(identity_failures / max(sample, 1), 4) if sample else None,
            "execution_miss_rate": round(execution_misses / max(sample, 1), 4) if sample else None,
            "oracle_divergence_rate": round(oracle_divergences / max(sample, 1), 4) if sample else None,
            "opportunity_type_performance": opportunity_type_performance,
        }

    def _create_active_policy(
        self,
        metrics: dict[str, object],
        sample_size: int,
        window_start: datetime | None,
        window_end: datetime | None,
    ) -> ActivePolicyVersionRecord:
        for row in self._session.query(ActivePolicyVersionRecord).filter_by(status="active").all():
            row.status = "superseded"

        execution_miss_rate = float(metrics.get("execution_miss_rate") or 0.0)
        identity_failure_rate = float(metrics.get("identity_failure_rate") or 0.0)
        false_positive_rate = float(metrics.get("false_positive_rate") or 0.0)
        policy_version = f"policy-calibrated-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        court_thresholds = {
            "court_min_fill_probability": round(min(0.95, 0.55 + execution_miss_rate), 4),
            "court_max_composite_risk": round(max(0.1, 0.45 - false_positive_rate * 0.2), 4),
        }
        risk_weights = {
            "semantic": round(1.0 + identity_failure_rate, 4),
            "execution": round(1.0 + execution_miss_rate, 4),
            "oracle": round(1.0 + float(metrics.get("oracle_divergence_rate") or 0.0), 4),
        }
        solver_penalties = {
            "identity_penalty": round(identity_failure_rate, 4),
            "execution_penalty": round(execution_miss_rate, 4),
        }
        execution_calibration = {
            "edge_capture": float(metrics.get("edge_capture") or 0.0),
            "execution_miss_rate": execution_miss_rate,
        }
        row = ActivePolicyVersionRecord(
            policy_version=policy_version,
            status="active",
            provenance={
                "source": "calibration_service",
                "sample_size": sample_size,
                "input_window_start": window_start.isoformat() if window_start else None,
                "input_window_end": window_end.isoformat() if window_end else None,
            },
            court_thresholds=court_thresholds,
            risk_weights=risk_weights,
            solver_penalties=solver_penalties,
            execution_calibration=execution_calibration,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        return row

    def _persist_scorecards(self, calibration_run_id: uuid.UUID, performance: dict[str, float]) -> None:
        for opportunity_type, score in performance.items():
            self._session.add(
                OpportunityTypeScorecardRecord(
                    calibration_run_id=calibration_run_id,
                    opportunity_type=opportunity_type,
                    scorecard_json={"mean_realized_pnl": score},
                )
            )
            if score < 0:
                strategy_key = f"{opportunity_type}:negative-realized-pnl"
                existing = self._session.query(StrategyKillListRecord).filter_by(strategy_key=strategy_key).first()
                if existing is None:
                    self._session.add(
                        StrategyKillListRecord(
                            strategy_key=strategy_key,
                            warning_level="warning",
                            reason="Repeated false positives or negative realized PnL",
                            evidence={"mean_realized_pnl": score},
                            active=True,
                        )
                    )

    def _persist_feedback(self, calibration_run_id, autopsies_by_candidate, positions, candidates) -> None:
        for position in positions:
            candidate = candidates.get(position.candidate_id)
            if candidate is None:
                continue
            labels = Counter(
                label
                for autopsy in autopsies_by_candidate.get(position.candidate_id, [])
                for label in (autopsy.labels or [])
            )
            if labels.get("false_equivalence", 0):
                self._session.add(
                    IdentityFeedbackEventRecord(
                        calibration_run_id=calibration_run_id,
                        candidate_id=position.candidate_id,
                        feedback_type="false_equivalence",
                        payload={"count": labels["false_equivalence"]},
                    )
                )
            if labels.get("execution_miss", 0) or labels.get("stale_quote_miss", 0):
                self._session.add(
                    ExecutionFeedbackEventRecord(
                        calibration_run_id=calibration_run_id,
                        candidate_id=position.candidate_id,
                        feedback_type="execution_miss",
                        payload={"labels": dict(labels)},
                    )
                )
            if labels.get("oracle_mismatch", 0) or any(
                autopsy.resolution_type == "ORACLE_DIVERGENCE"
                for autopsy in autopsies_by_candidate.get(position.candidate_id, [])
            ):
                self._session.add(
                    OracleFeedbackEventRecord(
                        calibration_run_id=calibration_run_id,
                        candidate_id=position.candidate_id,
                        feedback_type="oracle_mismatch",
                        payload={"labels": dict(labels)},
                    )
                )
            if float(position.actual_pnl or 0.0) <= 0:
                self._session.add(
                    SolverFeedbackEventRecord(
                        calibration_run_id=calibration_run_id,
                        candidate_id=position.candidate_id,
                        feedback_type="false_positive",
                        payload={"opportunity_type": candidate.opportunity_type},
                    )
                )
