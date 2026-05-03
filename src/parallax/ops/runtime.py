from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from parallax.config import settings
from parallax.db.models import RawMarket
from parallax.ops.schemas import ReadinessReport, RuntimeControlState


def runtime_control_state() -> RuntimeControlState:
    venue_pauses = {
        "polymarket": settings.runtime_pause_polymarket,
        "kalshi": settings.runtime_pause_kalshi,
    }
    degraded_read_only = settings.runtime_degraded_read_only or settings.runtime_global_pause
    return RuntimeControlState(
        global_pause=settings.runtime_global_pause,
        venue_pauses=venue_pauses,
        semantic_analysis_disabled=settings.runtime_semantic_analysis_disabled,
        live_execution_enabled=settings.runtime_live_execution_enabled,
        degraded_read_only_mode=degraded_read_only,
        max_exposure=settings.runtime_max_exposure,
        max_daily_loss=settings.runtime_max_daily_loss,
        max_candidate_concurrency=settings.runtime_max_candidate_concurrency,
    )


def build_readiness_payload(session: Session) -> ReadinessReport:
    now = datetime.now(timezone.utc)
    freshness_threshold_minutes = settings.provider_freshness_threshold_minutes

    count_rows = (
        session.query(RawMarket.platform, func.count(RawMarket.id))
        .group_by(RawMarket.platform)
        .all()
    )
    latest_rows = (
        session.query(RawMarket.platform, func.max(RawMarket.updated_at))
        .group_by(RawMarket.platform)
        .all()
    )

    counts = {str(platform): int(count) for platform, count in count_rows if platform is not None}
    latest_by_platform = {str(platform): updated_at for platform, updated_at in latest_rows if platform is not None}

    provider_checks = {
        "polymarket": _provider_check(
            enabled=True,
            configured=True,
            latest_market_at=latest_by_platform.get("polymarket"),
            market_count=counts.get("polymarket", 0),
            freshness_threshold_minutes=freshness_threshold_minutes,
            now=now,
            provider="native",
        ),
        "kalshi": _provider_check(
            enabled=True,
            configured=True,
            latest_market_at=latest_by_platform.get("kalshi"),
            market_count=counts.get("kalshi", 0),
            freshness_threshold_minutes=freshness_threshold_minutes,
            now=now,
            provider="native",
        ),
    }

    semantic_available = bool(
        settings.anthropic_api_key.strip()
        and settings.anthropic_api_key.strip().lower() != "placeholder"
    )
    semantic_disabled = settings.runtime_semantic_analysis_disabled
    semantic_check = {
        "status": (
            "disabled"
            if semantic_disabled
            else "ok"
            if semantic_available
            else "misconfigured"
        ),
        "provider": "anthropic",
        "configured": semantic_available,
        "min_relation_confidence": settings.semantic_min_relation_confidence,
        "reason": (
            "runtime semantic analysis disable switch is active"
            if semantic_disabled
            else None if semantic_available else "missing anthropic credentials"
        ),
    }

    degraded_reasons: list[str] = []
    degraded = any(check["status"] not in {"ok", "disabled"} for check in provider_checks.values())
    for provider, check in provider_checks.items():
        if check["status"] == "misconfigured":
            degraded_reasons.append(f"{provider} provider missing credentials")
        elif check["status"] == "missing":
            degraded_reasons.append(f"{provider} provider has no persisted markets yet")
        elif check["status"] == "stale":
            degraded_reasons.append(f"{provider} provider breached freshness threshold")
    if semantic_check["status"] == "misconfigured":
        degraded = True
        degraded_reasons.append("semantic analysis unavailable due to missing credentials")
    elif semantic_check["status"] == "disabled":
        degraded = True
        degraded_reasons.append("semantic analysis disabled by runtime control")
    control_state = runtime_control_state()
    if control_state.global_pause:
        degraded = True
        degraded_reasons.append("global pause is active")
    if control_state.degraded_read_only_mode:
        degraded = True
        degraded_reasons.append("runtime is in degraded read-only mode")

    return ReadinessReport(
        status="ready" if not degraded else "degraded",
        database="ok",
        degraded_reasons=degraded_reasons,
        controls=control_state,
        checks={
            "semantic_analysis": semantic_check,
            "providers": provider_checks,
        },
    )


def _provider_check(
    *,
    enabled: bool,
    configured: bool,
    latest_market_at,
    market_count: int,
    freshness_threshold_minutes: int,
    now: datetime,
    provider: str,
) -> dict:
    if not enabled:
        status = "disabled"
        age_minutes = None
        reason = "provider disabled by config"
    elif not configured:
        status = "misconfigured"
        age_minutes = None
        reason = "credentials missing"
    elif latest_market_at is None or market_count == 0:
        status = "missing"
        age_minutes = None
        reason = "no persisted markets"
    else:
        age_minutes = round((now - latest_market_at).total_seconds() / 60, 2)
        status = "ok" if age_minutes <= freshness_threshold_minutes else "stale"
        reason = None if status == "ok" else "provider data is stale"

    return {
        "status": status,
        "provider": provider,
        "enabled": enabled,
        "configured": configured,
        "market_count": market_count,
        "latest_market_at": latest_market_at,
        "age_minutes": age_minutes,
        "freshness_threshold_minutes": freshness_threshold_minutes,
        "reason": reason,
    }
