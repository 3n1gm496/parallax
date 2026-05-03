from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.db.models import EventIdentityCluster, IdentityMatchReview, IdentityMetric
from parallax.identity.benchmark import BenchmarkRunner
from parallax.shared.schemas import IdentityResolutionStatus


class MetricsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def compute_and_persist(self) -> IdentityMetric:
        cluster_count = self._session.query(EventIdentityCluster).filter_by(status="active").count()
        verified_count = (
            self._session.query(IdentityMatchReview).filter_by(status=IdentityResolutionStatus.VERIFIED.value).count()
        )
        ambiguous_count = (
            self._session.query(IdentityMatchReview).filter_by(status=IdentityResolutionStatus.AMBIGUOUS.value).count()
        )
        benchmark = BenchmarkRunner(self._session).evaluate_all()
        metric = IdentityMetric(
            computed_at=datetime.now(timezone.utc),
            scorer_version="identity-v3",
            verified_count=verified_count,
            ambiguous_count=ambiguous_count,
            cluster_count=cluster_count,
            benchmark_accuracy=benchmark.accuracy if benchmark.total else None,
            metrics_json={
                "benchmark_total": benchmark.total,
                "benchmark_correct": benchmark.correct,
                "benchmark_wrong": benchmark.wrong,
                "benchmark_skipped": benchmark.skipped,
            },
        )
        self._session.add(metric)
        self._session.flush()
        return metric

    def latest(self) -> IdentityMetric | None:
        return self._session.query(IdentityMetric).order_by(IdentityMetric.computed_at.desc()).first()
