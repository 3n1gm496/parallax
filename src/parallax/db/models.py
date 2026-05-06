from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, JSON, Float, Boolean, Integer, ForeignKey, DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


_TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(_TZ, index=True, default=_now)
    __table_args__ = (
        Index("ix_audit_events_entity_lookup", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_events_time_type", "created_at", "event_type"),
    )


class RawMarket(Base):
    __tablename__ = "raw_markets"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # "{platform}:{market_id}"
    platform: Mapped[str] = mapped_column(String(50), index=True)
    market_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    resolution_criteria: Mapped[str] = mapped_column(Text)
    outcomes: Mapped[list] = mapped_column(JSON)
    outcome_prices: Mapped[list] = mapped_column(JSON)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    deadline: Mapped[datetime] = mapped_column(_TZ, index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)
    __table_args__ = (
        Index("ix_raw_markets_platform_group_deadline", "platform", "group_id", "deadline"),
        Index("ix_raw_markets_platform_updated_at", "platform", "updated_at"),
    )


class CompiledContract(Base):
    __tablename__ = "compiled_contracts"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    contract_json: Mapped[dict] = mapped_column(JSON)
    compiler_confidence: Mapped[float] = mapped_column(Float)
    compiler_version: Mapped[str] = mapped_column(String(100))
    compiled_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class CompiledProposition(Base):
    __tablename__ = "compiled_propositions"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), unique=True, index=True)
    proposition_json: Mapped[dict] = mapped_column(JSON)
    compiler_version: Mapped[str] = mapped_column(String(100))
    compiled_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    platform_group_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    resolution: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)
    __table_args__ = (
        Index("ix_canonical_events_domain_status", "domain", "status"),
    )


class CanonicalEventFrame(Base):
    __tablename__ = "canonical_event_frames"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    frame_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    frame_type: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    canonical_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_events.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)
    __table_args__ = (
        Index("ix_canonical_event_frames_domain_type", "domain", "frame_type"),
    )


class MarketEventLink(Base):
    __tablename__ = "market_event_links"
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), primary_key=True)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_events.id"), primary_key=True
    )
    link_reason: Mapped[str] = mapped_column(String(100), default="platform_group_key")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    linked_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_market_event_links_event", "canonical_event_id", "linked_at"),
    )


class IdentityMatchReview(Base):
    __tablename__ = "identity_match_reviews"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), unique=True, index=True)
    canonical_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("canonical_events.id"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="unresolved", index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scorer_version: Mapped[str] = mapped_column(String(100), default="identity-v2")
    review_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    __table_args__ = (
        Index("ix_identity_match_reviews_status_reviewed", "status", "reviewed_at"),
    )


class EventFrameMembership(Base):
    __tablename__ = "event_frame_memberships"
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), primary_key=True)
    frame_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_event_frames.id"), primary_key=True)
    membership_type: Mapped[str] = mapped_column(String(100), default="same_event_family")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_event_frame_memberships_frame", "frame_id", "created_at"),
    )


class MarketRelation(Base):
    __tablename__ = "market_relations"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_market_id: Mapped[str] = mapped_column(String(255), index=True)
    to_market_id: Mapped[str] = mapped_column(String(255), index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_market_relations_pair", "from_market_id", "to_market_id"),
    )


class LogicalRelation(Base):
    __tablename__ = "logical_relations"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_market_id: Mapped[str] = mapped_column(String(255), index=True)
    to_market_id: Mapped[str] = mapped_column(String(255), index=True)
    frame_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_event_frames.id"), nullable=True, index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    proof_status: Mapped[str] = mapped_column(String(50), default="verified", index=True)
    tradeable_relation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_logical_relations_pair", "from_market_id", "to_market_id"),
        Index("ix_logical_relations_tradeable", "tradeable_relation", "proof_status"),
    )


class LogicalRelationSet(Base):
    __tablename__ = "logical_relation_sets"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    set_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    frame_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("canonical_event_frames.id"), nullable=True, index=True)
    member_market_ids: Mapped[list] = mapped_column(JSON, default=list)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    proof_status: Mapped[str] = mapped_column(String(50), default="verified", index=True)
    tradeable_relation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_logical_relation_sets_tradeable", "tradeable_relation", "proof_status"),
        Index("ix_logical_relation_sets_frame_relation", "frame_id", "relation_type"),
    )


class RelationReview(Base):
    __tablename__ = "relation_reviews"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_market_id: Mapped[str] = mapped_column(String(255), index=True)
    to_market_id: Mapped[str] = mapped_column(String(255), index=True)
    proposed_relation_type: Mapped[str] = mapped_column(String(100), index=True)
    reviewed_relation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proof_status: Mapped[str] = mapped_column(String(50), default="needs_review")
    tradeable_relation: Mapped[bool] = mapped_column(Boolean, default=False)
    review_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class CounterexampleRecord(Base):
    __tablename__ = "counterexample_records"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    relation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("logical_relations.id"), nullable=True, index=True)
    review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("relation_reviews.id"), nullable=True, index=True)
    set_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    scenario_description: Mapped[str] = mapped_column(Text)
    resolution_a: Mapped[str] = mapped_column(String(20))
    resolution_b: Mapped[str] = mapped_column(String(20))
    why_different: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), default="recorded", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_counterexample_records_relation_status", "relation_id", "status"),
        Index("ix_counterexample_records_review_status", "review_id", "status"),
    )


class OpportunityCandidate(Base):
    __tablename__ = "opportunity_candidates"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_ids: Mapped[list] = mapped_column(JSON)
    payoff_matrix: Mapped[dict] = mapped_column(JSON)
    scenario_matrix_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    proof_object_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    solver_version: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    constraint_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    basket_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    false_arbitrage_label: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    opportunity_type: Mapped[str] = mapped_column(String(100), index=True)
    worst_case_payoff: Mapped[float] = mapped_column(Float)
    friction_bps: Mapped[int] = mapped_column(Integer)
    risk_scores: Mapped[dict] = mapped_column(JSON)
    court_decision: Mapped[str] = mapped_column(String(50), default="PENDING")
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    detected_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    __table_args__ = (
        Index("ix_opportunity_candidates_status_decision_detected", "status", "court_decision", "detected_at"),
        Index(
            "ix_opportunity_candidates_solver_dedupe",
            "status",
            "solver_version",
            "constraint_fingerprint",
        ),
    )


class CandidateDecisionSnapshot(Base):
    __tablename__ = "candidate_decision_snapshots"
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunity_candidates.id"), primary_key=True
    )
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    risk_score: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relation_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    simulation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    court_assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision_ledger_entry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    snapshot_version: Mapped[str] = mapped_column(String(100), default="decision-snapshot-v1")
    evaluated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    __table_args__ = (
        Index("ix_candidate_decision_snapshots_run_evaluated", "run_id", "evaluated_at"),
    )


class DecisionLedgerRecord(Base):
    __tablename__ = "decision_ledger_records"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    decision: Mapped[str] = mapped_column(String(50), index=True)
    source_of_truth: Mapped[str] = mapped_column(String(50), index=True)
    fallback_status: Mapped[str] = mapped_column(String(50), default="none", index=True)
    model_version: Mapped[str] = mapped_column(String(100), default="decision-ledger-v1")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_packet: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relation_proof: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    blocking_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    counterexamples: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    __table_args__ = (
        Index("ix_decision_ledger_records_candidate_evaluated", "candidate_id", "evaluated_at"),
        Index("ix_decision_ledger_records_run_evaluated", "run_id", "evaluated_at"),
    )


class RunProofRecord(Base):
    __tablename__ = "run_proofs"
    run_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    run_status: Mapped[str] = mapped_column(String(50), default="completed", index=True)
    started_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    config_fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    provider_fingerprints: Mapped[dict] = mapped_column(JSON, default=dict)
    readiness_checks: Mapped[dict] = mapped_column(JSON, default=dict)
    control_state: Mapped[dict] = mapped_column(JSON, default=dict)
    markets_ingested: Mapped[int] = mapped_column(Integer, default=0)
    market_counts_by_platform: Mapped[dict] = mapped_column(JSON, default=dict)
    contracts_compiled: Mapped[int] = mapped_column(Integer, default=0)
    events_resolved: Mapped[int] = mapped_column(Integer, default=0)
    relations_detected: Mapped[int] = mapped_column(Integer, default=0)
    candidates_found: Mapped[int] = mapped_column(Integer, default=0)
    candidates_watchlisted: Mapped[int] = mapped_column(Integer, default=0)
    positions_opened: Mapped[int] = mapped_column(Integer, default=0)
    positions_settled: Mapped[int] = mapped_column(Integer, default=0)
    fatal_errors: Mapped[list] = mapped_column(JSON, default=list)
    non_fatal_errors: Mapped[list] = mapped_column(JSON, default=list)
    proof_version: Mapped[str] = mapped_column(String(100), default="run-proof-v1")
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)
    __table_args__ = (
        Index("ix_run_proofs_status_completed", "run_status", "completed_at"),
    )


class SolverPolicyRecord(Base):
    __tablename__ = "solver_policies"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    solver_version: Mapped[str] = mapped_column(String(100), index=True)
    policy_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)


class SolverFixtureRecord(Base):
    __tablename__ = "solver_fixtures"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    fixture_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class SolverAuditRecordModel(Base):
    __tablename__ = "solver_audit_records"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunity_candidates.id"), nullable=True, index=True
    )
    constraint_fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    solver_version: Mapped[str] = mapped_column(String(100), index=True)
    policy_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), default="solved", index=True)
    audit_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)

    __table_args__ = (
        Index(
            "ix_solver_audit_records_fingerprint_solver",
            "constraint_fingerprint",
            "solver_version",
            "created_at",
        ),
    )


class ShadowCandidateObservation(Base):
    __tablename__ = "shadow_candidate_observations"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[str] = mapped_column(String(255), index=True)
    relation_key: Mapped[str] = mapped_column(String(255), index=True)
    relation_kind: Mapped[str] = mapped_column(String(50), index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    market_ids: Mapped[list] = mapped_column(JSON, default=list)
    identity_status: Mapped[str] = mapped_column(String(50), default="unresolved", index=True)
    identity_version: Mapped[str] = mapped_column(String(100), default="identity-v1")
    proof_status: Mapped[str] = mapped_column(String(50), default="needs_review", index=True)
    tradeable_relation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    solver_called: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    solver_skip_reason: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    solver_none_reason: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    displayed_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    executable_edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    worst_case_payoff: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid_state_count: Mapped[int] = mapped_column(Integer, default=0)
    impossible_state_count: Mapped[int] = mapped_column(Integer, default=0)
    false_arbitrage_label: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    min_profit_threshold: Mapped[float] = mapped_column(Float, default=0.005)
    rejected_by_threshold: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejected_by_identity: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejected_by_false_arbitrage: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rejected_by_dedup: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    execution_evidence_missing: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    blocking_gates: Mapped[list] = mapped_column(JSON, default=list)
    relaxation_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    minimal_relaxation: Mapped[list] = mapped_column(JSON, default=list)
    dangerous_relaxation: Mapped[bool] = mapped_column(Boolean, default=False)
    persisted_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunity_candidates.id"), nullable=True, index=True
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)

    __table_args__ = (
        Index(
            "ix_shadow_candidate_observations_run_kind_created",
            "run_id",
            "relation_kind",
            "created_at",
        ),
        Index(
            "ix_shadow_candidate_observations_run_relation_key",
            "run_id",
            "relation_key",
        ),
    )


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"), index=True)
    certificate_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="OPEN")
    legs_json: Mapped[list] = mapped_column(JSON)   # list[Leg.model_dump()]
    opened_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    actual_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (
        Index("ix_paper_positions_candidate_status_opened", "candidate_id", "status", "opened_at"),
        Index("ix_paper_positions_legs_gin", "legs_json", postgresql_using="gin"),
    )


class AutopsyRecord(Base):
    __tablename__ = "autopsy_records"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"), index=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    actual_resolution: Mapped[dict] = mapped_column(JSON)  # {market_id: "Yes"|"No"|"N/A"}
    resolution_type: Mapped[str] = mapped_column(String(100), index=True)
    identity_error: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    __table_args__ = (
        Index("ix_autopsy_records_candidate_created", "candidate_id", "created_at"),
        Index("ix_autopsy_records_identity_error_created", "identity_error", "created_at"),
    )


class VenueToken(Base):
    __tablename__ = "venue_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(50), index=True)
    raw_market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(512), index=True)
    outcome: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)

    __table_args__ = (
        UniqueConstraint("platform", "raw_market_id", "outcome", name="uq_venue_tokens_platform_market_outcome"),
    )


class OrderbookSnapshotRecord(Base):
    __tablename__ = "orderbook_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(50), index=True)
    raw_market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outcome: Mapped[str] = mapped_column(String(50))
    captured_at: Mapped[datetime] = mapped_column(_TZ, index=True)
    bid_levels: Mapped[list] = mapped_column(JSON, default=list)
    ask_levels: Mapped[list] = mapped_column(JSON, default=list)
    mid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_bid_depth: Mapped[float] = mapped_column(Float, default=0.0)
    total_ask_depth: Mapped[float] = mapped_column(Float, default=0.0)
    fetcher_version: Mapped[str] = mapped_column(String(50), default="snapshot-v1")
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)

    __table_args__ = (
        Index("ix_orderbook_snapshots_market_captured", "raw_market_id", "captured_at"),
    )


class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)


class CanonicalSource(Base):
    __tablename__ = "canonical_sources"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(100), default="unknown", index=True)
    trust_level: Mapped[float] = mapped_column(Float, default=0.5)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class CanonicalDeadline(Base):
    __tablename__ = "canonical_deadlines"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bucket_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    resolution_date: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    deadline_type: Mapped[str] = mapped_column(String(50), default="exact")
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class EventTemplate(Base):
    __tablename__ = "event_templates"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    predicate_template: Mapped[str] = mapped_column(Text)
    canonical_predicate: Mapped[str] = mapped_column(String(100), index=True)
    example_titles: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)


class EventIdentityCluster(Base):
    __tablename__ = "event_identity_clusters"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_key: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    identity_type: Mapped[str] = mapped_column(String(100), index=True)
    primary_canonical_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("canonical_events.id"),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_version: Mapped[str] = mapped_column(String(100), default="identity-v3")
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_event_identity_clusters_type_status", "identity_type", "status"),
    )


class IdentityClusterMember(Base):
    __tablename__ = "identity_cluster_members"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event_identity_clusters.id"), index=True)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("canonical_events.id"), index=True)
    raw_market_id: Mapped[str | None] = mapped_column(ForeignKey("raw_markets.id"), nullable=True, index=True)
    member_role: Mapped[str] = mapped_column(String(50), default="secondary")
    added_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    added_by: Mapped[str] = mapped_column(String(100), default="system")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("cluster_id", "raw_market_id", name="uq_cluster_member"),
        Index("ix_identity_cluster_members_cluster", "cluster_id", "added_at"),
    )


class IdentitySplitMergeHistory(Base):
    __tablename__ = "identity_split_merge_history"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(50), index=True)
    source_cluster_ids: Mapped[list] = mapped_column(JSON)
    target_cluster_ids: Mapped[list] = mapped_column(JSON)
    triggered_by: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    acted_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)


class IdentityReviewActionRecord(Base):
    __tablename__ = "identity_review_actions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event_identity_clusters.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    acted_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)


class IdentityTrainingExample(Base):
    __tablename__ = "identity_training_examples"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_id_a: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    market_id_b: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    label: Mapped[str] = mapped_column(String(50))
    identity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    labeler: Mapped[str] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)

    __table_args__ = (
        UniqueConstraint("market_id_a", "market_id_b", name="uq_training_example_pair"),
    )


class IdentityBenchmarkCase(Base):
    __tablename__ = "identity_benchmark_cases"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    market_id_a: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    market_id_b: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    expected_label: Mapped[str] = mapped_column(String(50))
    expected_identity_type: Mapped[str] = mapped_column(String(100))
    difficulty: Mapped[str] = mapped_column(String(50), default="medium")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class IdentityMetric(Base):
    __tablename__ = "identity_metrics"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    computed_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    scorer_version: Mapped[str] = mapped_column(String(100))
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1: Mapped[float | None] = mapped_column(Float, nullable=True)
    false_merge_count: Mapped[int] = mapped_column(Integer, default=0)
    false_split_count: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous_count: Mapped[int] = mapped_column(Integer, default=0)
    verified_count: Mapped[int] = mapped_column(Integer, default=0)
    cluster_count: Mapped[int] = mapped_column(Integer, default=0)
    benchmark_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)


class TradeProofCertificateRecord(Base):
    __tablename__ = "trade_proof_certificates"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    certificate_version: Mapped[str] = mapped_column(String(100), default="trade-proof-certificate-v1")
    certificate_status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    market_data_snapshot_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    compiled_contract_versions: Mapped[list] = mapped_column(JSON, default=list)
    contract_fingerprints: Mapped[dict] = mapped_column(JSON, default=dict)
    identity_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    identity_status: Mapped[str] = mapped_column(String(50), default="unresolved")
    identity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    identity_provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    identity_cluster_ids: Mapped[list] = mapped_column(JSON, default=list)
    relation_proof_ids: Mapped[list] = mapped_column(JSON, default=list)
    relation_set_ids: Mapped[list] = mapped_column(JSON, default=list)
    solver_proof_object_hash: Mapped[str] = mapped_column(String(255), index=True)
    payoff_matrix_hash: Mapped[str] = mapped_column(String(255))
    scenario_matrix_hash: Mapped[str] = mapped_column(String(255))
    orderbook_snapshot_ids: Mapped[list] = mapped_column(JSON, default=list)
    execution_model: Mapped[str] = mapped_column(String(50), default="heuristic")
    execution_simulation_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    court_decision_snapshot_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    risk_score_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    config_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_fingerprints: Mapped[dict] = mapped_column(JSON, default=dict)
    invalidation_conditions: Mapped[list] = mapped_column(JSON, default=list)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    supersedes_certificate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trade_proof_certificates.id"), nullable=True, index=True
    )
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_trade_proof_certificates_candidate_status_generated", "candidate_id", "certificate_status", "generated_at"),
    )


class CalibrationRunRecord(Base):
    __tablename__ = "calibration_runs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(50), default="insufficient_data", index=True)
    input_window_start: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    input_window_end: Mapped[datetime | None] = mapped_column(_TZ, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)
    activated_policy_version: Mapped[str | None] = mapped_column(String(100), nullable=True)


class ActivePolicyVersionRecord(Base):
    __tablename__ = "active_policy_versions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_version: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="candidate", index=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    court_thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    solver_penalties: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_calibration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now, index=True)


class OpportunityTypeScorecardRecord(Base):
    __tablename__ = "opportunity_type_scorecards"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calibration_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calibration_runs.id"), index=True)
    opportunity_type: Mapped[str] = mapped_column(String(100), index=True)
    scorecard_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class StrategyKillListRecord(Base):
    __tablename__ = "strategy_kill_list"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_key: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    warning_level: Mapped[str] = mapped_column(String(50), default="watch", index=True)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class IdentityFeedbackEventRecord(Base):
    __tablename__ = "identity_feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calibration_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calibration_runs.id"), nullable=True, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunity_candidates.id"), nullable=True, index=True)
    feedback_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class SolverFeedbackEventRecord(Base):
    __tablename__ = "solver_feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calibration_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calibration_runs.id"), nullable=True, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunity_candidates.id"), nullable=True, index=True)
    feedback_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class ExecutionFeedbackEventRecord(Base):
    __tablename__ = "execution_feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calibration_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calibration_runs.id"), nullable=True, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunity_candidates.id"), nullable=True, index=True)
    feedback_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class OracleFeedbackEventRecord(Base):
    __tablename__ = "oracle_feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calibration_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calibration_runs.id"), nullable=True, index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunity_candidates.id"), nullable=True, index=True)
    feedback_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)


class HedgeIntentRecord(Base):
    __tablename__ = "hedge_intents"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"), index=True)
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("paper_positions.id"), nullable=True, index=True)
    legs_to_unwind: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)  # pending, completed, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ, default=_now, onupdate=_now)
