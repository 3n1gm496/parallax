from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, JSON, Float, Boolean, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(index=True, default=_now)
    # No update / delete allowed — enforced at repository level


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
    deadline: Mapped[datetime] = mapped_column(index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now)


class CompiledContract(Base):
    __tablename__ = "compiled_contracts"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    contract_json: Mapped[dict] = mapped_column(JSON)
    compiler_confidence: Mapped[float] = mapped_column(Float)
    compiler_version: Mapped[str] = mapped_column(String(100))
    compiled_at: Mapped[datetime] = mapped_column(default=_now)


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    platform_group_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    resolution: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now)


class MarketEventLink(Base):
    __tablename__ = "market_event_links"
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), primary_key=True)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_events.id"), primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(default=_now)


class MarketRelation(Base):
    __tablename__ = "market_relations"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_market_id: Mapped[str] = mapped_column(String(255), index=True)
    to_market_id: Mapped[str] = mapped_column(String(255), index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(100))  # "stage1_constraint" | "stage2_llm"
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OpportunityCandidate(Base):
    __tablename__ = "opportunity_candidates"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_ids: Mapped[list] = mapped_column(JSON)
    payoff_matrix: Mapped[dict] = mapped_column(JSON)
    opportunity_type: Mapped[str] = mapped_column(String(100), index=True)
    worst_case_payoff: Mapped[float] = mapped_column(Float)
    friction_bps: Mapped[int] = mapped_column(Integer)
    risk_scores: Mapped[dict] = mapped_column(JSON)
    court_decision: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    detected_at: Mapped[datetime] = mapped_column(default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"))
    status: Mapped[str] = mapped_column(String(50), default="OPEN")
    legs_json: Mapped[list] = mapped_column(JSON)   # list[Leg.model_dump()]
    opened_at: Mapped[datetime] = mapped_column(default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    actual_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class AutopsyRecord(Base):
    __tablename__ = "autopsy_records"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"))
    position_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    actual_resolution: Mapped[dict] = mapped_column(JSON)  # {market_id: "Yes"|"No"|"N/A"}
    resolution_type: Mapped[str] = mapped_column(String(100), index=True)
    identity_error: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)
