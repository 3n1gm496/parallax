def test_all_models_importable():
    from parallax.db.models import (
        AuditEvent, RawMarket, CompiledContract, CanonicalEvent,
        MarketEventLink, MarketRelation, OpportunityCandidate,
        PaperPosition, AutopsyRecord,
    )
    assert AuditEvent.__tablename__ == "audit_events"
    assert RawMarket.__tablename__ == "raw_markets"
    assert OpportunityCandidate.__tablename__ == "opportunity_candidates"
