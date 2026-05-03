from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.config import settings
from parallax.db.models import AutopsyRecord
from parallax.ops.schemas import PolicyRecommendation, PolicyReport
from parallax.ops.service import get_backtest_replay_payload, get_identity_review_queue_payload

_POLICY_VERSION = "policy-v1"


def get_policy_report_payload(session: Session, *, replay_limit: int = 100, queue_limit: int = 100) -> PolicyReport:
    backtest = get_backtest_replay_payload(session, limit=replay_limit)
    identity_queue = get_identity_review_queue_payload(session, limit=queue_limit)
    autopsy_rows = session.query(AutopsyRecord).all()

    total_autopsies = max(len(autopsy_rows), 1)
    identity_invalidations = sum(1 for row in backtest.rows if row.replay_outcome == "identity_invalidated")
    oracle_invalidations = sum(1 for row in backtest.rows if row.replay_outcome == "oracle_invalidated")
    execution_misses = sum(
        1
        for row in backtest.rows
        if "execution_miss" in row.autopsy_labels or "stale_quote_miss" in row.autopsy_labels
    )
    semantic_failures = sum(
        1
        for row in autopsy_rows
        if any(label in {"false_equivalence", "ambiguity_miss"} for label in (row.labels or []))
    )
    oracle_failures = sum(
        1 for row in autopsy_rows if row.resolution_type == "ORACLE_DIVERGENCE" or "oracle_mismatch" in (row.labels or [])
    )
    liquidity_failures = sum(1 for row in autopsy_rows if "stale_quote_miss" in (row.labels or []))

    identity_pressure = round(identity_invalidations / max(len(backtest.rows), 1), 4)
    semantic_pressure = round(semantic_failures / total_autopsies, 4)
    execution_pressure = round(execution_misses / max(len(backtest.rows), 1), 4)
    liquidity_pressure = round(liquidity_failures / total_autopsies, 4)
    oracle_pressure = round(oracle_failures / total_autopsies, 4)

    recommendations: list[PolicyRecommendation] = []
    recommendations.extend(
        _maybe_recommend(
            component="semantic_min_relation_confidence",
            pressure=semantic_pressure,
            current_value=settings.semantic_min_relation_confidence,
            suggested_step=0.05,
            basis=[
                f"semantic/autopsy pressure {semantic_pressure:.4f}",
                f"identity invalidations {identity_invalidations}",
            ],
        )
    )
    recommendations.extend(
        _maybe_recommend(
            component="court_min_fill_probability",
            pressure=execution_pressure,
            current_value=settings.court_min_fill_probability,
            suggested_step=0.05,
            basis=[
                f"execution replay pressure {execution_pressure:.4f}",
                f"recent stale/execution misses {execution_misses}",
            ],
        )
    )
    recommendations.extend(
        _maybe_recommend(
            component="court_max_composite_risk",
            pressure=oracle_pressure,
            current_value=settings.court_max_composite_risk,
            suggested_step=-0.05,
            basis=[
                f"oracle/autopsy pressure {oracle_pressure:.4f}",
                f"recent oracle invalidations {oracle_invalidations}",
            ],
        )
    )
    if identity_pressure >= 0.1 or len(identity_queue.items) >= 5:
        recommendations.append(
            PolicyRecommendation(
                component="identity_review_queue",
                priority="high" if identity_pressure >= 0.25 else "medium",
                pressure=max(identity_pressure, min(len(identity_queue.items) / 20, 1.0)),
                current_value=float(len(identity_queue.items)),
                recommended_value=0.0,
                action="review and relabel ambiguous identity cases before approving new strict semantic opportunities",
                basis=[
                    f"queue size {len(identity_queue.items)}",
                    f"identity replay pressure {identity_pressure:.4f}",
                ],
            )
        )

    return PolicyReport(
        generated_at=datetime.now(timezone.utc),
        policy_version=_POLICY_VERSION,
        calibration_policy_version="risk-v2",
        identity_risk_pressure=identity_pressure,
        semantic_risk_pressure=semantic_pressure,
        execution_risk_pressure=execution_pressure,
        liquidity_risk_pressure=liquidity_pressure,
        oracle_risk_pressure=oracle_pressure,
        review_queue_size=len(identity_queue.items),
        recent_identity_invalidations=identity_invalidations,
        recent_oracle_invalidations=oracle_invalidations,
        recommendations=recommendations,
    )


def _maybe_recommend(
    *,
    component: str,
    pressure: float,
    current_value: float,
    suggested_step: float,
    basis: list[str],
) -> list[PolicyRecommendation]:
    if pressure < 0.1:
        return []
    priority = "high" if pressure >= 0.25 else "medium"
    recommended_value = current_value + suggested_step
    if suggested_step > 0:
        recommended_value = min(1.0, recommended_value)
        action = "tighten the threshold to reduce false positives"
    else:
        recommended_value = max(0.0, recommended_value)
        action = "lower the maximum tolerated risk to reduce invalidated approvals"
    return [
        PolicyRecommendation(
            component=component,
            priority=priority,
            pressure=pressure,
            current_value=round(current_value, 4),
            recommended_value=round(recommended_value, 4),
            action=action,
            basis=basis,
        )
    ]
