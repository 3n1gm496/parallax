from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from parallax.api.app import app
from parallax.api.deps import get_read_session, get_write_session
from parallax.calibration.service import CalibrationService
from parallax.candidates.repository import CandidateRepository
from parallax.certificates.service import CertificateService
from parallax.court.service import CourtService
from parallax.db.models import (
    ActivePolicyVersionRecord,
    AutopsyRecord,
    OpportunityCandidate,
    OracleFeedbackEventRecord,
    PaperPosition,
    RawMarket,
    RunProofRecord,
    ShadowCandidateObservation,
    StrategyKillListRecord,
)
from parallax.shared.schemas import (
    CourtAssessment,
    CourtDecision,
    DecisionGate,
    IdentityResolutionStatus,
    Leg,
    OpportunityType,
    OutcomeState,
    OutcomeStateSpace,
    PayoffMatrix,
    ProofObject,
    RelationEvidenceResponse,
    RelationType,
    RiskScore,
    Scenario,
    SimulationResult,
)
from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot
from parallax.simulator.service import SimulatorService
from parallax.solver.service import GeneralizedPayoffSolver
from parallax.tracker.service import TrackerService


def _market(market_id: str, platform: str, yes_price: float) -> RawMarket:
    return RawMarket(
        id=f"{platform}:{market_id}",
        platform=platform,
        market_id=market_id,
        title=f"{market_id} title",
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        category="politics",
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source="official",
        raw_payload={},
    )


def _payoff_matrix(a_id: str, b_id: str) -> PayoffMatrix:
    return PayoffMatrix(
        legs=[
            Leg(market_id=a_id, side="YES", price=0.40, quantity=1.0, cost=0.40, platform="polymarket"),
            Leg(market_id=b_id, side="NO", price=0.45, quantity=1.0, cost=0.45, platform="kalshi"),
        ],
        total_cost=0.85,
        scenarios=[
            Scenario(name="state-0", description="A YES, B NO", payoff=0.15, is_breaking=False),
            Scenario(name="state-1", description="A NO, B YES", payoff=0.15, is_breaking=False),
        ],
        worst_case_payoff=0.15,
        best_case_payoff=0.15,
        breaking_scenario=None,
        opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
        friction_bps=10,
    )


def _scenario_matrix(a_id: str, b_id: str) -> OutcomeStateSpace:
    return OutcomeStateSpace(
        market_ids=[a_id, b_id],
        valid_states=[
            OutcomeState(state_id="state-0", assignments={a_id: "YES", b_id: "NO"}),
            OutcomeState(state_id="state-1", assignments={a_id: "NO", b_id: "YES"}),
        ],
        impossible_states=[],
        enumeration_mode="custom",
    )


def _proof_object(a_id: str, b_id: str, *, proof_status: str = "verified", policy_key: str = "default") -> ProofObject:
    return ProofObject(
        solver_version="generalized-payoff-v1",
        constraint_fingerprint=f"fp-{uuid.uuid4().hex[:8]}",
        policy_key=policy_key,
        policy_version=policy_key,
        identity_version="identity-v3-runtime",
        proof_status=proof_status,
        relation_types=[RelationType.EQUIVALENT],
        relation_set_keys=[],
        assumptions=["identity_status=verified"],
        executable_pricing_used=True,
        valid_states=_scenario_matrix(a_id, b_id).valid_states,
        payoff_by_state={"state-0": 0.15, "state-1": 0.15},
        audit_trail=[{"step": "price", "displayed_edge": 0.15}],
    )


def _simulation_result(*, candidate_id: str, execution_model: str = "snapshot_based") -> SimulationResult:
    return SimulationResult(
        candidate_id=candidate_id,
        displayed_edge=0.15,
        executable_edge=0.12,
        simulated_pnl=0.12,
        friction_bps=10,
        fill_probability=0.62,
        is_executable=True,
        note="integration fixture",
        estimated_slippage_bps=12,
        estimated_slippage_cost=0.01,
        execution_quality="medium",
        venue_breakdown={"platforms": ["polymarket", "kalshi"]},
        execution_model=execution_model,  # type: ignore[arg-type]
        snapshot_ids=["snap-1"] if execution_model == "snapshot_based" else [],
        depth_support=True if execution_model == "snapshot_based" else None,
        quote_staleness_seconds=3.0 if execution_model == "snapshot_based" else None,
        partial_fill_risk=0.12,
    )


def _court_assessment() -> CourtAssessment:
    return CourtAssessment(
        decision=CourtDecision.APPROVED,
        simulated_pnl=0.12,
        fill_probability=0.62,
        composite_risk=0.4,
        reasons=["integration fixture approval"],
        opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
        relation_type=RelationType.EQUIVALENT,
        gates=[DecisionGate(name="simulated_pnl", status="pass", observed="0.12", threshold="> 0")],
        policy_version="court-v2",
    )


def _relation(a_id: str, b_id: str, identity_status: IdentityResolutionStatus, *, identity_version: str = "identity-v3-runtime") -> RelationEvidenceResponse:
    return RelationEvidenceResponse(
        from_market_id=a_id,
        to_market_id=b_id,
        relation_type=RelationType.EQUIVALENT,
        confidence=0.98,
        created_by="integration-test",
        tradeable_relation=True,
        proof_status="verified",
        identity_status=identity_status,
        identity_version=identity_version,
        identity_confidence=0.98 if identity_status == IdentityResolutionStatus.VERIFIED else 0.4,
        identity_provenance={"cluster_ids": ["cluster-1"], "links": {a_id: {}, b_id: {}}},
    )


def _risk() -> RiskScore:
    return RiskScore.combine(
        oracle=0.4,
        deadline=0.3,
        semantic=0.3,
        execution=0.4,
        liquidity=0.4,
        cancellation=0.2,
        source_trust=0.4,
    )


def _seed_candidate(
    session,
    *,
    proof_status: str = "verified",
    identity_status: IdentityResolutionStatus = IdentityResolutionStatus.VERIFIED,
    identity_version: str = "identity-v3-runtime",
    execution_model: str = "snapshot_based",
) -> str:
    suffix = uuid.uuid4().hex[:8]
    a_id = f"polymarket:omega-a-{suffix}"
    b_id = f"kalshi:omega-b-{suffix}"
    session.add_all([_market(f"omega-a-{suffix}", "polymarket", 0.40), _market(f"omega-b-{suffix}", "kalshi", 0.55)])
    session.flush()

    repo = CandidateRepository(session)
    candidate = repo.create(
        market_ids=[a_id, b_id],
        payoff_matrix=_payoff_matrix(a_id, b_id),
        opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
        risk_scores=_risk().model_dump(),
        scenario_matrix=_scenario_matrix(a_id, b_id),
        proof_object=_proof_object(a_id, b_id, proof_status=proof_status),
        solver_version="generalized-payoff-v1",
        constraint_fingerprint=f"cf-{uuid.uuid4().hex[:8]}",
        basket={"solver": "bounded-deterministic-v1"},
        false_arbitrage_label=None if proof_status != "false_arbitrage" else "proof_needs_review",
    )
    repo.update_decision(str(candidate.id), CourtDecision.APPROVED)
    repo.upsert_decision_snapshot(
        str(candidate.id),
        run_id="run-int-1",
        risk_score=_risk(),
        relation_evidence=_relation(a_id, b_id, identity_status, identity_version=identity_version),
        simulation_result=_simulation_result(candidate_id=str(candidate.id), execution_model=execution_model),
        court_assessment=_court_assessment(),
    )
    session.flush()
    return str(candidate.id)


def _client(test_session):
    def _read_override():
        yield test_session

    def _write_override():
        yield test_session

    app.dependency_overrides[get_read_session] = _read_override
    app.dependency_overrides[get_write_session] = _write_override
    return TestClient(app)


def test_trade_proof_certificate_enforcement_and_api(test_session):
    candidate_id = _seed_candidate(test_session)
    service = CertificateService(test_session)

    issued = service.issue(candidate_id)
    first_generated_at = issued.generated_at
    reissued = service.issue(candidate_id)
    assert reissued.id == issued.id
    assert reissued.generated_at == first_generated_at

    position = TrackerService(test_session).open_position(candidate_id)
    assert position is not None
    assert position.certificate_id == issued.id

    second_candidate_id = _seed_candidate(test_session)
    second_issued = service.issue(second_candidate_id)
    successor = service.supersede(str(second_issued.id))
    assert successor.supersedes_certificate_id == second_issued.id

    client = _client(test_session)
    try:
        certificate_response = client.get(f"/api/candidates/{candidate_id}/certificate")
        assert certificate_response.status_code == 200
        assert certificate_response.json()["certificate_status"] == "issued"

        list_response = client.get("/api/ops/certificates")
        assert list_response.status_code == 200
        assert any(item["candidate_id"] == candidate_id for item in list_response.json()["items"])
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_candidate_diagnostic_endpoints(test_session):
    run_id = "run-diag-api"
    test_session.add(
        RunProofRecord(
            run_id=run_id,
            run_status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            config_fingerprint="cfg",
            provider_fingerprints={},
            readiness_checks={},
            control_state={},
            markets_ingested=2,
            market_counts_by_platform={"polymarket": 1, "kalshi": 1},
            contracts_compiled=2,
            events_resolved=1,
            relations_detected=1,
            candidates_found=0,
            candidates_watchlisted=0,
            positions_opened=0,
            positions_settled=0,
            fatal_errors=[],
            non_fatal_errors=[],
        )
    )
    test_session.add(
        ShadowCandidateObservation(
            run_id=run_id,
            relation_key="rel-1",
            relation_kind="relation",
            relation_type="equivalent",
            market_ids=["polymarket:one", "kalshi:two"],
            identity_status="ambiguous",
            identity_version="identity-v3-runtime",
            proof_status="needs_review",
            tradeable_relation=False,
            solver_called=False,
            solver_skip_reason="identity_not_verified",
            solver_none_reason=None,
            displayed_edge=None,
            executable_edge=None,
            worst_case_payoff=None,
            valid_state_count=0,
            impossible_state_count=0,
            false_arbitrage_label=None,
            min_profit_threshold=0.005,
            rejected_by_threshold=False,
            rejected_by_identity=True,
            rejected_by_false_arbitrage=False,
            rejected_by_dedup=False,
            execution_evidence_missing=True,
            blocking_gates=["identity_gate"],
            relaxation_flags={"identity_gate_relaxed": True},
            minimal_relaxation=["identity_gate_relaxed"],
            dangerous_relaxation=True,
            persisted_candidate_id=None,
            metadata_json={},
        )
    )
    test_session.commit()

    client = _client(test_session)
    try:
        funnel = client.get("/api/ops/candidate-funnel")
        assert funnel.status_code == 200
        assert funnel.json()["run_id"] == run_id

        shadow = client.get("/api/ops/shadow-candidates")
        assert shadow.status_code == 200
        assert shadow.json()["rows"][0]["blocking_gates"] == ["identity_gate"]

        sensitivity = client.get("/api/ops/sensitivity")
        assert sensitivity.status_code == 200
        assert sensitivity.json()["diagnostic_only"] is True
    finally:
        client.close()
        app.dependency_overrides.clear()


def test_trade_proof_certificate_blocks_unproven_candidates(test_session):
    missing_identity = _seed_candidate(test_session, identity_status=IdentityResolutionStatus.UNRESOLVED)
    false_arbitrage = _seed_candidate(test_session, proof_status="false_arbitrage")
    legacy_identity = _seed_candidate(test_session, identity_version="identity-v2")
    missing_proof = _seed_candidate(test_session)
    missing_proof_row = test_session.get(OpportunityCandidate, uuid.UUID(missing_proof))
    assert missing_proof_row is not None
    missing_proof_row.proof_object_json = None
    test_session.flush()

    service = CertificateService(test_session)

    try:
        service.issue(missing_identity)
        assert False, "expected identity gate to block certificate issuance"
    except ValueError as exc:
        assert "identity is not verified" in str(exc)

    try:
        service.issue(false_arbitrage)
        assert False, "expected false arbitrage gate to block certificate issuance"
    except ValueError as exc:
        assert "false arbitrage" in str(exc)

    try:
        service.issue(missing_proof)
        assert False, "expected missing proof object to block certificate issuance"
    except ValueError as exc:
        assert "proof chain is incomplete" in str(exc)

    assert TrackerService(test_session).open_position(legacy_identity) is None


def test_calibration_activation_persists_feedback_and_changes_runtime_behavior(test_session):
    baseline_candidate_id = _seed_candidate(test_session)
    baseline_row = test_session.get(OpportunityCandidate, uuid.UUID(baseline_candidate_id))
    assert baseline_row is not None
    baseline_row.opportunity_type = OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING.value
    baseline_row.payoff_matrix["opportunity_type"] = OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING.value
    test_session.flush()
    baseline_simulated = SimulatorService(test_session).simulate(baseline_candidate_id).simulated_pnl
    baseline_decision = CourtService(test_session).assess(baseline_candidate_id).decision
    assert baseline_decision == CourtDecision.APPROVED

    insufficient = CalibrationService(test_session).run()
    assert insufficient.run.status == "insufficient_data"
    assert insufficient.active_policy is None

    for index, actual_pnl in enumerate([0.03, -0.04, -0.02], start=1):
        candidate_id = _seed_candidate(test_session)
        candidate_uuid = uuid.UUID(candidate_id)
        test_session.add(
            PaperPosition(
                candidate_id=candidate_uuid,
                certificate_id=None,
                status="CLOSED",
                legs_json=[],
                closed_at=datetime.now(timezone.utc),
                actual_pnl=actual_pnl,
            )
        )
        labels = ["false_equivalence"] if index == 1 else ["execution_miss", "oracle_mismatch"]
        resolution_type = "ORACLE_DIVERGENCE" if index == 2 else "CORRECT"
        test_session.add(
            AutopsyRecord(
                candidate_id=candidate_uuid,
                position_id=None,
                actual_resolution={},
                resolution_type=resolution_type,
                identity_error=index == 1,
                labels=labels,
            )
        )
    test_session.flush()

    calibrated = CalibrationService(test_session).run()
    assert calibrated.run.status == "completed"
    assert calibrated.active_policy is not None
    assert calibrated.active_policy.status == "active"
    assert test_session.query(OracleFeedbackEventRecord).count() >= 1
    assert test_session.query(StrategyKillListRecord).count() >= 1

    after_simulated = SimulatorService(test_session).simulate(baseline_candidate_id).simulated_pnl
    after_decision = CourtService(test_session).assess(baseline_candidate_id).decision
    assert after_simulated < baseline_simulated
    assert after_decision != CourtDecision.APPROVED


def test_solver_reads_active_policy_penalties(test_session):
    test_session.add(
        ActivePolicyVersionRecord(
            policy_version="policy-calibrated-test",
            status="active",
            provenance={"source": "test"},
            court_thresholds={},
            risk_weights={},
            solver_penalties={"identity_penalty": 0.4, "execution_penalty": 0.3},
            execution_calibration={},
        )
    )
    test_session.flush()

    solver = GeneralizedPayoffSolver(session=test_session)

    def _ob(market_id: str, platform: str, mid: float) -> OrderbookSnapshot:
        spread = 0.005
        return OrderbookSnapshot(
            id=f"snap:{market_id}",
            platform=platform,
            market_id=market_id,
            outcome="YES",
            captured_at=datetime.now(timezone.utc),
            bids=OrderbookSide(levels=[OrderbookLevel(price=mid - spread / 2, size=200.0)]),
            asks=OrderbookSide(levels=[OrderbookLevel(price=mid + spread / 2, size=200.0)]),
            mid_price=mid,
            spread_bps=spread * 10_000,
        )

    result = solver.solve(
        markets=[_market("omega-a-solver", "polymarket", 0.40), _market("omega-b-solver", "kalshi", 0.55)],
        relation_evidence=_relation("polymarket:omega-a-solver", "kalshi:omega-b-solver", IdentityResolutionStatus.VERIFIED),
        relations=[],
        orderbooks={
            "polymarket:omega-a-solver": _ob("polymarket:omega-a-solver", "polymarket", 0.40),
            "kalshi:omega-b-solver":     _ob("kalshi:omega-b-solver",     "kalshi",     0.55),
        },
    )

    assert solver._policy.policy_key == "policy-calibrated-test"
    assert solver._policy.metadata["source"] == "active_policy"
    assert result is not None
