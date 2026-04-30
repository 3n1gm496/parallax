"""Smoke tests for API routes using FastAPI TestClient."""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from parallax.api.app import app
from parallax.api.deps import get_session
from parallax.db.models import AuditEvent, OpportunityCandidate
from parallax.shared.schemas import (
    CourtDecision,
    Leg,
    OpportunityType,
    PayoffMatrix,
    Scenario,
)


def _payoff_matrix() -> PayoffMatrix:
    return PayoffMatrix(
        legs=[Leg(market_id="pm:a", side="YES", price=0.45, platform="pm")],
        total_cost=0.45,
        scenarios=[Scenario(name="win", description="win", payoff=0.05, is_breaking=False)],
        worst_case_payoff=0.05,
        best_case_payoff=0.05,
        breaking_scenario=None,
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        friction_bps=10,
    )


def _candidate() -> OpportunityCandidate:
    m = _payoff_matrix()
    return OpportunityCandidate(
        id=uuid.uuid4(),
        market_ids=["pm:a"],
        payoff_matrix=m.model_dump(),
        opportunity_type=OpportunityType.PURE_ARBITRAGE.value,
        worst_case_payoff=0.05,
        friction_bps=10,
        risk_scores={},
        court_decision=CourtDecision.PENDING.value,
        detected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _mock_session():
    session = MagicMock()
    session.commit = MagicMock()
    session.close = MagicMock()
    return session


class TestHealthRoute:
    def test_health_returns_ok(self):
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestCandidatesRoute:
    def test_list_candidates_empty(self):
        session = _mock_session()
        session.query.return_value.filter_by.return_value.all.return_value = []
        app.dependency_overrides[get_session] = lambda: session
        client = TestClient(app)
        resp = client.get("/api/candidates")
        assert resp.status_code == 200
        assert resp.json() == []
        app.dependency_overrides.clear()

    def test_get_candidate_not_found(self):
        session = _mock_session()
        session.get.return_value = None
        app.dependency_overrides[get_session] = lambda: session
        client = TestClient(app)
        resp = client.get(f"/api/candidates/{uuid.uuid4()}")
        assert resp.status_code == 404
        app.dependency_overrides.clear()


class TestAuditRoute:
    def test_list_audit_empty(self):
        session = _mock_session()
        session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
        app.dependency_overrides[get_session] = lambda: session
        client = TestClient(app)
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        assert resp.json() == []
        app.dependency_overrides.clear()
