from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parallax.execution.replay_stats import ReplayStatisticsService, ReplayStats


def _make_session(rows: list[tuple]) -> MagicMock:
    """rows: list of (actual_pnl: float, simulation_result: dict)"""
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.all.return_value = rows
    session.execute.return_value = execute_result
    return session


def test_get_stats_returns_none_when_no_history():
    session = _make_session([])
    svc = ReplayStatisticsService(session)
    assert svc.get_stats("pure_arbitrage") is None


def test_get_stats_returns_none_when_below_min_history():
    rows = [
        (0.05, {"executable_edge": 0.10}),
        (-0.02, {"executable_edge": 0.08}),
    ]
    session = _make_session(rows)
    svc = ReplayStatisticsService(session)
    assert svc.get_stats("pure_arbitrage") is None


def test_get_stats_computes_win_rate_correctly():
    rows = [
        (0.05, {"executable_edge": 0.10}),   # profitable
        (0.03, {"executable_edge": 0.08}),   # profitable
        (-0.01, {"executable_edge": 0.06}),  # loss
    ]
    session = _make_session(rows)
    svc = ReplayStatisticsService(session)
    stats = svc.get_stats("pure_arbitrage")
    assert stats is not None
    assert stats.n_settled == 3
    assert stats.win_rate == round(2 / 3, 4)


def test_get_stats_computes_mean_edge_capture():
    rows = [
        (0.05, {"executable_edge": 0.10}),   # capture = 0.5
        (0.08, {"executable_edge": 0.10}),   # capture = 0.8
        (0.04, {"executable_edge": 0.10}),   # capture = 0.4
    ]
    session = _make_session(rows)
    svc = ReplayStatisticsService(session)
    stats = svc.get_stats("pure_arbitrage")
    assert stats is not None
    expected = round((0.5 + 0.8 + 0.4) / 3, 4)
    assert stats.mean_edge_capture == expected


def test_get_stats_skips_rows_with_zero_stored_edge():
    rows = [
        (0.05, {"executable_edge": 0.0}),    # zero edge — skip
        (0.03, {"executable_edge": 0.08}),
        (0.02, {"executable_edge": 0.06}),
        (0.01, {"executable_edge": 0.04}),
    ]
    session = _make_session(rows)
    svc = ReplayStatisticsService(session)
    stats = svc.get_stats("pure_arbitrage")
    assert stats is not None
    captures = [0.03 / 0.08, 0.02 / 0.06, 0.01 / 0.04]
    expected = round(sum(captures) / len(captures), 4)
    assert stats.mean_edge_capture == expected


def test_get_stats_returns_none_when_all_edges_are_zero():
    rows = [
        (0.05, {"executable_edge": 0.0}),
        (0.03, {"executable_edge": 0.0}),
        (0.02, {"executable_edge": 0.0}),
    ]
    session = _make_session(rows)
    svc = ReplayStatisticsService(session)
    assert svc.get_stats("pure_arbitrage") is None


def test_get_stats_handles_missing_simulation_result():
    rows = [
        (0.05, None),
        (0.03, {"executable_edge": 0.08}),
        (0.02, {"executable_edge": 0.06}),
        (0.01, {"executable_edge": 0.04}),
    ]
    session = _make_session(rows)
    svc = ReplayStatisticsService(session)
    stats = svc.get_stats("pure_arbitrage")
    assert stats is not None
    captures = [0.03 / 0.08, 0.02 / 0.06, 0.01 / 0.04]
    expected = round(sum(captures) / len(captures), 4)
    assert stats.mean_edge_capture == expected
