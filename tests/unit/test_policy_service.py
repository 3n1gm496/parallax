from unittest.mock import MagicMock, patch

from parallax.policy.service import get_policy_report_payload


def test_get_policy_report_builds_recommendations_from_replay_and_queue():
    session = MagicMock()
    autopsy_row = MagicMock(labels=["false_equivalence", "oracle_mismatch"], resolution_type="ORACLE_DIVERGENCE")
    session.query.return_value.all.return_value = [autopsy_row]
    with (
        patch("parallax.policy.service.get_backtest_replay_payload") as mock_backtest,
        patch("parallax.policy.service.get_identity_review_queue_payload") as mock_queue,
    ):
        mock_backtest.return_value = MagicMock(
            rows=[
                MagicMock(
                    replay_outcome="identity_invalidated",
                    autopsy_labels=["execution_miss"],
                ),
                MagicMock(
                    replay_outcome="oracle_invalidated",
                    autopsy_labels=["stale_quote_miss"],
                ),
            ]
        )
        mock_queue.return_value = MagicMock(items=[MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()])

        report = get_policy_report_payload(session)

    assert report.policy_version == "policy-v1"
    assert report.review_queue_size == 5
    assert report.recent_identity_invalidations == 1
    assert report.recent_oracle_invalidations == 1
    assert report.recommendations
    assert any(item.component == "identity_review_queue" for item in report.recommendations)
