from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


def test_execution_report_schema_importable():
    from parallax.ops.schemas import ExecutionCoverageStats, ExecutionReport
    r = ExecutionReport(
        orderbook_enabled=True,
        coverage=[
            ExecutionCoverageStats(
                platform="polymarket",
                venue_token_count=42,
                snapshot_count=10,
                latest_snapshot_at=None,
            )
        ],
        total_venue_tokens=42,
        total_snapshots=10,
        execution_model_distribution={"heuristic": 8, "snapshot_based": 2},
        avg_quote_staleness_seconds=12.5,
        depth_support_rate=0.9,
    )
    assert r.total_venue_tokens == 42
    assert r.execution_model_distribution["snapshot_based"] == 2


def test_readiness_report_has_orderbook_fields():
    from parallax.ops.schemas import ReadinessReport
    fields = ReadinessReport.model_fields
    assert "orderbook_enabled" in fields
    assert "venue_token_count" in fields


def _make_sim_json(execution_model="heuristic", staleness=None, depth_support=None):
    d = {"execution_model": execution_model, "quote_staleness_seconds": staleness}
    if depth_support is not None:
        d["depth_support"] = depth_support
    return d


def test_execution_report_service_empty_db():
    from parallax.ops.execution_report import ExecutionReportService

    session = MagicMock()
    vt_result = MagicMock()
    vt_result.all.return_value = []
    snap_result = MagicMock()
    snap_result.all.return_value = []
    ds_result = MagicMock()
    ds_result.scalars.return_value = MagicMock()
    ds_result.scalars.return_value.all.return_value = []
    session.execute.side_effect = [vt_result, snap_result, ds_result]

    report = ExecutionReportService.build(session)
    assert report.total_venue_tokens == 0
    assert report.total_snapshots == 0
    assert report.execution_model_distribution == {}
    assert report.avg_quote_staleness_seconds is None
    assert report.depth_support_rate is None


def test_execution_report_service_computes_distribution():
    from parallax.ops.execution_report import ExecutionReportService

    session = MagicMock()

    vt_result = MagicMock()
    vt_result.all.return_value = [("polymarket", 5)]

    snap_result = MagicMock()
    ts = datetime(2026, 5, 3, tzinfo=timezone.utc)
    snap_result.all.return_value = [("polymarket", 3, ts)]

    ds_result = MagicMock()
    ds_result.scalars.return_value = MagicMock()
    ds_result.scalars.return_value.all.return_value = [
        _make_sim_json("snapshot_based", staleness=10.0, depth_support=True),
        _make_sim_json("snapshot_based", staleness=20.0, depth_support=False),
        _make_sim_json("heuristic"),
    ]
    session.execute.side_effect = [vt_result, snap_result, ds_result]

    report = ExecutionReportService.build(session)

    assert report.total_venue_tokens == 5
    assert report.total_snapshots == 3
    assert report.execution_model_distribution["snapshot_based"] == 2
    assert report.execution_model_distribution["heuristic"] == 1
    assert report.avg_quote_staleness_seconds == 15.0
    assert report.depth_support_rate == 0.5
    assert report.coverage[0].platform == "polymarket"
    assert report.coverage[0].venue_token_count == 5
