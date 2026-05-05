from __future__ import annotations

from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from parallax.config import settings
from parallax.db.models import VenueToken, OrderbookSnapshotRecord, CandidateDecisionSnapshot
from parallax.ops.schemas import ExecutionCoverageStats, ExecutionReport


class ExecutionReportService:
    @staticmethod
    def _execution_path_for_payload(payload: dict) -> str:
        path = payload.get("execution_path")
        if isinstance(path, str) and path:
            return path
        legacy_model = str(payload.get("execution_model") or "calibrated_model")
        if legacy_model == "heuristic":
            return "calibrated_model"
        if legacy_model == "snapshot_based":
            return "offline_validation"
        if legacy_model == "replay_based":
            return "offline_validation"
        if legacy_model == "degraded":
            return "degraded_fallback"
        return legacy_model

    @staticmethod
    def build(session: Session) -> ExecutionReport:
        vt_rows = session.execute(
            select(VenueToken.platform, func.count(VenueToken.id)).group_by(VenueToken.platform)
        ).all()
        vt_by_platform: dict[str, int] = {str(p): int(c) for p, c in vt_rows}

        snap_rows = session.execute(
            select(
                OrderbookSnapshotRecord.platform,
                func.count(OrderbookSnapshotRecord.id),
                func.max(OrderbookSnapshotRecord.captured_at),
            ).group_by(OrderbookSnapshotRecord.platform)
        ).all()
        snap_by_platform: dict[str, tuple] = {
            str(p): (int(c), latest) for p, c, latest in snap_rows
        }

        all_platforms = sorted(set(vt_by_platform) | set(snap_by_platform))
        coverage = [
            ExecutionCoverageStats(
                platform=p,
                venue_token_count=vt_by_platform.get(p, 0),
                snapshot_count=snap_by_platform.get(p, (0, None))[0],
                latest_snapshot_at=snap_by_platform.get(p, (0, None))[1],
            )
            for p in all_platforms
        ]

        sim_jsons = session.execute(
            select(CandidateDecisionSnapshot.simulation_result)
            .where(CandidateDecisionSnapshot.simulation_result.isnot(None))
            .order_by(desc(CandidateDecisionSnapshot.evaluated_at))
            .limit(500)
        ).scalars().all()

        model_counts: dict[str, int] = {}
        path_counts: dict[str, int] = {}
        staleness_values: list[float] = []
        depth_true = 0
        depth_total = 0

        for sim in sim_jsons:
            if not isinstance(sim, dict):
                continue
            em = sim.get("execution_model", "heuristic")
            model_counts[em] = model_counts.get(em, 0) + 1
            ep = ExecutionReportService._execution_path_for_payload(sim)
            path_counts[ep] = path_counts.get(ep, 0) + 1
            qs = sim.get("quote_staleness_seconds")
            if qs is not None:
                staleness_values.append(float(qs))
            ds = sim.get("depth_support")
            if ds is not None:
                depth_total += 1
                if ds:
                    depth_true += 1

        return ExecutionReport(
            orderbook_enabled=settings.orderbook_enabled,
            coverage=coverage,
            total_venue_tokens=sum(vt_by_platform.values()),
            total_snapshots=sum(c for c, _ in snap_by_platform.values()),
            execution_model_distribution=model_counts,
            execution_path_distribution=path_counts,
            avg_quote_staleness_seconds=sum(staleness_values) / len(staleness_values) if staleness_values else None,
            depth_support_rate=depth_true / depth_total if depth_total > 0 else None,
        )
