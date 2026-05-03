def test_all_models_importable():
    from parallax.db.models import (
        AuditEvent, CounterexampleRecord, IdentityMatchReview, LogicalRelationSet, OpportunityCandidate, RawMarket, RunProofRecord,
    )
    assert AuditEvent.__tablename__ == "audit_events"
    assert CounterexampleRecord.__tablename__ == "counterexample_records"
    assert IdentityMatchReview.__tablename__ == "identity_match_reviews"
    assert LogicalRelationSet.__tablename__ == "logical_relation_sets"
    assert RawMarket.__tablename__ == "raw_markets"
    assert OpportunityCandidate.__tablename__ == "opportunity_candidates"
    assert RunProofRecord.__tablename__ == "run_proofs"


def test_venue_token_model_exists():
    from parallax.db.models import VenueToken

    row = VenueToken(
        platform="polymarket",
        raw_market_id="0xabc123",
        token_id="71321045679252212594626385532706912750332728571942532289631379312455583992745",
        outcome="YES",
    )
    assert row.platform == "polymarket"
    assert row.outcome == "YES"


def test_orderbook_snapshot_record_model_exists():
    from parallax.db.models import OrderbookSnapshotRecord
    from datetime import datetime, timezone

    row = OrderbookSnapshotRecord(
        platform="kalshi",
        raw_market_id="KXSOME-24NOV-B0.5",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bid_levels=[{"price": 0.45, "size": 100.0}],
        ask_levels=[{"price": 0.47, "size": 200.0}],
        mid_price=0.46,
        spread_bps=43.5,
        total_bid_depth=100.0,
        total_ask_depth=200.0,
    )
    assert row.platform == "kalshi"
    assert row.mid_price == 0.46
