from __future__ import annotations

from datetime import datetime, timezone

from parallax.ops.schemas import RunProof, RunProofListResponse, RunSummary
from parallax.ops.service import _latest_completed_run_summary, _semantic_check_status


def _run_summary(run_id: str, run_status: str) -> RunSummary:
    now = datetime(2026, 5, 4, tzinfo=timezone.utc)
    return RunSummary(
        run_id=run_id,
        run_status=run_status,
        started_at=now,
        completed_at=now,
        markets_ingested=0,
        market_counts_by_platform={},
        contracts_compiled=0,
        events_resolved=0,
        relations_detected=0,
        candidates_found=0,
        candidates_watchlisted=0,
        positions_opened=0,
        positions_settled=0,
        config_fingerprint="cfg",
        provider_fingerprints={},
        errors=[],
    )


def _run_proof(run_id: str, run_status: str) -> RunProof:
    now = datetime(2026, 5, 4, tzinfo=timezone.utc)
    return RunProof(
        run_id=run_id,
        run_status=run_status,
        started_at=now,
        completed_at=now,
        config_fingerprint="cfg",
        provider_fingerprints={},
        readiness_checks={},
        control_state={},
        markets_ingested=0,
        market_counts_by_platform={},
        contracts_compiled=0,
        events_resolved=0,
        relations_detected=0,
        candidates_found=0,
        candidates_watchlisted=0,
        positions_opened=0,
        positions_settled=0,
        fatal_errors=[],
        non_fatal_errors=[],
        proof_version="run-proof-v1",
    )


def test_latest_completed_run_summary_skips_running(monkeypatch):
    running = _run_proof("run-running", "running")
    completed = _run_proof("run-completed", "completed")

    monkeypatch.setattr(
        "parallax.ops.service.list_run_proofs_payload",
        lambda session, limit=20: RunProofListResponse(runs=[running, completed]),
    )

    result = _latest_completed_run_summary(session=None)

    assert result is not None
    assert result.run_id == "run-completed"


def test_latest_completed_run_summary_falls_back_to_running(monkeypatch):
    running = _run_proof("run-running", "running")

    monkeypatch.setattr(
        "parallax.ops.service.list_run_proofs_payload",
        lambda session, limit=20: RunProofListResponse(runs=[running]),
    )

    result = _latest_completed_run_summary(session=None)

    assert result is not None
    assert result.run_id == "run-running"


def test_semantic_check_status_reads_runtime_key():
    readiness = type("Readiness", (), {"checks": {"semantic_analysis": {"status": "ok"}}})()

    assert _semantic_check_status(readiness) == "ok"


def test_semantic_check_status_falls_back_to_legacy_key():
    readiness = type("Readiness", (), {"checks": {"semantic": {"status": "disabled"}}})()

    assert _semantic_check_status(readiness) == "disabled"
