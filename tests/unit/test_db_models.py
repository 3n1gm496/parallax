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
