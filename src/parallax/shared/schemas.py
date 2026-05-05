from __future__ import annotations
import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeBps = Annotated[int, Field(ge=0)]


def _coerce_json_list(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return []
    if not text.startswith("["):
        return value

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return value
    return parsed


class RelationType(str, Enum):
    EQUIVALENT = "equivalent"
    DUPLICATE = "duplicate"
    SUBSET = "subset"
    SUPERSET = "superset"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    EXHAUSTIVE = "exhaustive"
    EXHAUSTIVE_PARTITION = "exhaustive_partition"
    PREREQUISITE = "prerequisite"
    INVERSE = "inverse"
    SAME_EVENT_DIFFERENT_DEADLINE = "same_event_different_deadline"
    SAME_EVENT_DIFFERENT_ORACLE = "same_event_different_oracle"
    SAME_EVENT_DIFFERENT_SOURCE = "same_event_different_source"
    SAME_EVENT_FAMILY = "same_event_family"
    SAME_EVENT_INDEPENDENT = "same_event_independent"
    RELATED_BUT_NOT_TRADEABLE = "related_but_not_tradeable"
    CORRELATED_ONLY = "correlated_only"
    NOT_RELATED = "not_related"


class OpportunityType(str, Enum):
    PURE_ARBITRAGE = "pure_arbitrage"
    NEAR_ARBITRAGE = "near_arbitrage"
    SEMANTIC_ARBITRAGE = "semantic_arbitrage"
    SUBSET_VIOLATION = "subset_violation"
    DUPLICATE_DIVERGENCE = "duplicate_divergence"
    MUTUALLY_EXCLUSIVE_MISPRICING = "mutually_exclusive_mispricing"
    EXHAUSTIVE_SET_MISPRICING = "exhaustive_set_mispricing"
    SETTLEMENT_YIELD = "settlement_yield"
    ASYMMETRIC_STRUCTURAL_BET = "asymmetric_structural_bet"
    FALSE_ARBITRAGE = "false_arbitrage"


class CourtDecision(str, Enum):
    APPROVED = "APPROVED"
    WATCHLIST = "WATCHLIST"
    REJECTED = "REJECTED"
    ABSTAINED = "ABSTAINED"
    PENDING = "PENDING"
    PAPER_TRADE = "PAPER_TRADE"
    CANDIDATE_FOR_LIVE = "CANDIDATE_FOR_LIVE"


class IdentityResolutionStatus(str, Enum):
    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


class IdentityType(str, Enum):
    EQUIVALENT = "equivalent"
    DUPLICATE = "duplicate"
    SAME_EVENT = "same_event"
    DUPLICATE_MARKET = "duplicate_market"
    NEAR_DUPLICATE = "near_duplicate"
    SUBSET = "subset"
    SUPERSET = "superset"
    SAME_EVENT_DIFF_SOURCE = "same_event_diff_source"
    SAME_EVENT_DIFF_ORACLE = "same_event_diff_oracle"
    SAME_EVENT_DIFF_DEADLINE = "same_event_diff_deadline"
    CORRELATED = "correlated"
    FALSE_EQUIVALENCE = "false_equivalence"


class IdentityClusterStatus(str, Enum):
    ACTIVE = "active"
    SPLIT = "split"
    MERGED_INTO = "merged_into"
    ARCHIVED = "archived"


class ClusterMemberRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class IdentityReviewAction(str, Enum):
    CONFIRM = "confirm"
    REJECT = "reject"
    SPLIT = "split"
    MERGE = "merge"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


class RawMarketData(BaseModel):
    platform: str
    market_id: str
    title: str
    description: str
    resolution_criteria: str
    outcomes: list[str]
    outcome_prices: list[float]
    category: str | None = None
    group_id: str | None = None
    deadline: datetime
    is_closed: bool
    resolution_source: str | None = None
    raw_payload: dict
    token_ids: dict[str, str] = Field(default_factory=dict)


class AmbiguityFlag(BaseModel):
    term: str
    description: str


class Counterexample(BaseModel):
    scenario_description: str
    resolution_a: Literal["YES", "NO", "AMBIGUOUS"]
    resolution_b: Literal["YES", "NO", "AMBIGUOUS"]
    why_different: str


class EvidencePacket(BaseModel):
    packet_id: str | None = None
    source_of_truth: Literal[
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] = "calibrated_model"
    fallback_status: Literal["none", "degraded", "offline_validation"] = "none"
    model_version: str = "evidence-packet-v1"
    confidence: Probability | None = None
    blocking_reason: str | None = None
    counterexamples: list[Counterexample] = Field(default_factory=list)
    evidence: dict[str, object] = Field(default_factory=dict)


class RelationProof(EvidencePacket):
    relation_type: RelationType | None = None
    proof_status: Literal["verified", "rejected", "needs_review"] = "needs_review"
    tradeable_relation: bool = False
    relation_signals: dict[str, object] = Field(default_factory=dict)
    identity_provenance: dict[str, object] | None = None
    identity_status: IdentityResolutionStatus = IdentityResolutionStatus.UNRESOLVED
    identity_version: str = "identity-v2"
    frame_id: str | None = None
    set_key: str | None = None
    member_market_ids: list[str] = Field(default_factory=list)


class IdentityResolutionBundle(EvidencePacket):
    candidate_retrieval: dict[str, object] = Field(default_factory=dict)
    rerank_result: dict[str, object] = Field(default_factory=dict)
    cluster_governance: dict[str, object] = Field(default_factory=dict)
    resolved_cluster_ids: list[str] = Field(default_factory=list)
    unresolved_cluster_ids: list[str] = Field(default_factory=list)


class ExecutionEvidence(EvidencePacket):
    execution_model: str = "calibrated_model"
    execution_path: Literal[
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] = "calibrated_model"
    legacy_execution_model: str | None = None
    quote_staleness_seconds: float | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    depth_support: bool | None = None
    partial_fill_risk: float = 0.0
    captured_quotes: list[dict[str, object]] = Field(default_factory=list)


class DecisionLedgerEntry(BaseModel):
    candidate_id: str
    run_id: str | None = None
    evaluated_at: datetime
    decision: CourtDecision
    source_of_truth: Literal[
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] = "calibrated_model"
    fallback_status: Literal["none", "degraded", "offline_validation"] = "none"
    model_version: str = "decision-ledger-v1"
    confidence: Probability | None = None
    score: float | None = None
    input_packet: EvidencePacket | None = None
    relation_proof: RelationProof | None = None
    execution_evidence: ExecutionEvidence | None = None
    blocking_reason: str | None = None
    counterexamples: list[Counterexample] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class ContractSchema(BaseModel):
    yes_conditions: list[str]
    no_conditions: list[str]
    exclusions: list[str]
    ambiguity_terms: list[AmbiguityFlag]
    counterexamples: list[Counterexample]
    compiler_confidence: Probability   # 0.0–1.0; calibrated over time
    canonical_subject: str | None = None
    canonical_predicate: str | None = None
    canonical_object: str | None = None
    comparator: str | None = None
    threshold_value: str | None = None
    threshold_comparator: str | None = None
    threshold: str | None = None
    temporal_focus: str | None = None
    temporal_deadline: str | None = None
    time_scope: str | None = None
    oracle_focus: str | None = None
    oracle_scope: str | None = None
    resolution_criteria: str | None = None
    resolution_exclusions: list[str] = Field(default_factory=list)
    cancellation_conditions: list[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative", "unknown"] = "unknown"
    proposition_family: str | None = None
    partition_hint: bool = False
    semantic_tags: list[str] = Field(default_factory=list)

    @field_validator(
        "yes_conditions",
        "no_conditions",
        "exclusions",
        "ambiguity_terms",
        "counterexamples",
        "resolution_exclusions",
        "cancellation_conditions",
        "semantic_tags",
        mode="before",
    )
    @classmethod
    def _normalize_list_like_fields(cls, value: Any) -> Any:
        return _coerce_json_list(value)

    @model_validator(mode="after")
    def _sync_semantic_aliases(self) -> "ContractSchema":
        if self.threshold_comparator is None:
            self.threshold_comparator = self.comparator
        if self.comparator is None:
            self.comparator = self.threshold_comparator
        if self.threshold is None:
            self.threshold = self.threshold_value
        if self.threshold_value is None:
            self.threshold_value = self.threshold
        if self.time_scope is None:
            self.time_scope = self.temporal_deadline or self.temporal_focus
        if self.oracle_scope is None:
            self.oracle_scope = self.oracle_focus
        if not self.resolution_exclusions:
            self.resolution_exclusions = list(self.exclusions)
        if self.polarity == "unknown" and self.canonical_predicate:
            self.polarity = "negative" if str(self.canonical_predicate).startswith("not_") else "positive"
        return self

    def semantic_hash(self) -> str:
        """Compute a deterministic hash of the core semantic properties."""
        payload = {
            "yes_conditions": sorted(self.yes_conditions),
            "no_conditions": sorted(self.no_conditions),
            "canonical_subject": self.canonical_subject,
            "canonical_predicate": self.canonical_predicate,
            "canonical_object": self.canonical_object,
            "threshold": self.threshold,
            "time_scope": self.time_scope,
            "resolution_criteria": self.resolution_criteria,
            "resolution_exclusions": sorted(self.resolution_exclusions or []),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class CompiledPropositionSchema(BaseModel):
    raw_market_id: str
    canonical_subject: str
    canonical_predicate: str
    canonical_object: str | None = None
    comparator: str | None = None
    threshold_value: str | None = None
    threshold_comparator: str | None = None
    threshold: str | None = None
    temporal_focus: str | None = None
    temporal_deadline: str | None = None
    time_scope: str | None = None
    oracle_focus: str | None = None
    oracle_scope: str | None = None
    resolution_exclusions: list[str] = Field(default_factory=list)
    cancellation_conditions: list[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative", "unknown"] = "unknown"
    proposition_family: str
    partition_hint: bool = False
    semantic_tags: list[str] = Field(default_factory=list)
    compiler_confidence: Probability

    @field_validator("semantic_tags", "resolution_exclusions", "cancellation_conditions", mode="before")
    @classmethod
    def _normalize_semantic_tags(cls, value: Any) -> Any:
        return _coerce_json_list(value)

    @model_validator(mode="after")
    def _sync_semantic_aliases(self) -> "CompiledPropositionSchema":
        if self.threshold_comparator is None:
            self.threshold_comparator = self.comparator
        if self.comparator is None:
            self.comparator = self.threshold_comparator
        if self.threshold is None:
            self.threshold = self.threshold_value
        if self.threshold_value is None:
            self.threshold_value = self.threshold
        if self.time_scope is None:
            self.time_scope = self.temporal_deadline or self.temporal_focus
        if self.oracle_scope is None:
            self.oracle_scope = self.oracle_focus
        if self.polarity == "unknown" and self.canonical_predicate:
            self.polarity = "negative" if str(self.canonical_predicate).startswith("not_") else "positive"
        return self


class CanonicalEventFrameSchema(BaseModel):
    frame_id: str
    frame_key: str
    frame_type: str
    title: str
    domain: str
    canonical_event_id: str | None = None
    market_ids: list[str] = Field(default_factory=list)


class LogicalRelationSchema(BaseModel):
    from_market_id: str
    to_market_id: str
    relation_type: RelationType
    proof_status: Literal["verified", "rejected", "needs_review"]
    tradeable_relation: bool = False
    confidence: Probability
    created_by: str
    evidence: dict[str, object] = Field(default_factory=dict)
    frame_id: str | None = None


class LogicalRelationSetSchema(BaseModel):
    relation_set_id: str | None = None
    set_key: str
    member_market_ids: list[str] = Field(default_factory=list)
    relation_type: RelationType
    proof_status: Literal["verified", "rejected", "needs_review"]
    tradeable_relation: bool = False
    confidence: Probability
    created_by: str
    evidence: dict[str, object] = Field(default_factory=dict)
    frame_id: str | None = None


class TradeabilityAssessment(BaseModel):
    tradeable_relation: bool = False
    proof_status: Literal["verified", "rejected", "needs_review"] = "needs_review"
    venue_constraints: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    required_counterexample_types: list[str] = Field(default_factory=list)
    assessment_version: str = "tradeability-v1"


class CounterexampleRecord(BaseModel):
    relation_id: str | None = None
    review_id: str | None = None
    relation_type: RelationType
    set_key: str | None = None
    scenario_description: str
    resolution_a: Literal["YES", "NO", "AMBIGUOUS"]
    resolution_b: Literal["YES", "NO", "AMBIGUOUS"]
    why_different: str
    source: str
    status: Literal["none_found", "recorded", "dismissed"] = "recorded"
    created_by: str
    metadata: dict[str, object] = Field(default_factory=dict)


class Leg(BaseModel):
    market_id: str
    action: Literal["BUY", "SELL"] = "BUY"
    side: Literal["YES", "NO"] = "YES"
    price: Probability
    quantity: float = 1.0
    cost: float | None = None    # must be set explicitly when known; not auto-computed
    max_size: float | None = None  # limits tranche size for Depth-of-Book
    outcome: str | None = None   # human-readable outcome label, e.g. "Biden wins"
    platform: str | None = None
    token_id: str | None = None


class Scenario(BaseModel):
    name: str
    description: str
    is_breaking: bool = False   # True → this scenario breaks the trade thesis
    payoff: float               # net payoff after total_cost is already subtracted


class PayoffMatrix(BaseModel):
    legs: list[Leg]
    total_cost: float
    scenarios: list[Scenario]
    worst_case_payoff: float
    best_case_payoff: float
    breaking_scenario: Scenario | None  # must exist for any approved candidate
    opportunity_type: OpportunityType
    friction_bps: NonNegativeBps


class ScenarioConstraintModel(BaseModel):
    constraint_key: str
    relation_type: RelationType
    market_ids: list[str] = Field(default_factory=list)
    proof_status: Literal["verified", "rejected", "needs_review"] = "verified"
    tradeable_relation: bool = False
    identity_status: IdentityResolutionStatus = IdentityResolutionStatus.UNRESOLVED
    identity_version: str = "identity-v2"
    set_key: str | None = None
    frame_id: str | None = None
    provenance: dict[str, object] = Field(default_factory=dict)
    execution_context: dict[str, object] = Field(default_factory=dict)


class OutcomeState(BaseModel):
    state_id: str
    assignments: dict[str, Literal["YES", "NO"]]
    is_possible: bool = True
    violated_constraints: list[str] = Field(default_factory=list)
    explanation: str | None = None


class OutcomeStateSpace(BaseModel):
    market_ids: list[str] = Field(default_factory=list)
    valid_states: list[OutcomeState] = Field(default_factory=list)
    impossible_states: list[OutcomeState] = Field(default_factory=list)
    enumeration_mode: Literal["custom", "z3", "hybrid"] = "custom"
    blocked_reason: str | None = None
    breaking_state_ids: list[str] = Field(default_factory=list)


class SolverPolicy(BaseModel):
    policy_key: str = "default"
    solver_version: str = "generalized-payoff-v1"
    min_profit_after_friction: float = 0.005
    max_quotes_staleness_seconds: float = 60.0
    max_leg_count_for_custom_enumerator: int = 8
    require_verified_identity_for_tradeable: bool = True
    require_proof_for_persistence: bool = True
    capital_limit: float = 1.0
    require_executable_pricing_when_available: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


class ProofObject(BaseModel):
    solver_version: str
    constraint_fingerprint: str
    policy_key: str
    policy_version: str
    identity_version: str
    proof_status: Literal["verified", "degraded", "needs_review", "false_arbitrage"] = "verified"
    relation_types: list[RelationType] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    relation_set_keys: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    executable_pricing_used: bool = False
    false_arbitrage_label: str | None = None
    valid_states: list[OutcomeState] = Field(default_factory=list)
    impossible_scenarios: list[OutcomeState] = Field(default_factory=list)
    breaking_scenarios: list[Scenario] = Field(default_factory=list)
    payoff_by_state: dict[str, float] = Field(default_factory=dict)
    audit_trail: list[dict[str, object]] = Field(default_factory=list)
    evidence_packet: EvidencePacket | None = None


class SolverAuditRecord(BaseModel):
    constraint_fingerprint: str
    solver_version: str
    policy_key: str
    candidate_id: str | None = None
    status: Literal["solved", "blocked", "false_arbitrage"] = "solved"
    trace: dict[str, object] = Field(default_factory=dict)
    created_at: datetime | None = None


class SolverFixtureCase(BaseModel):
    case_key: str
    description: str
    relation_type: RelationType
    markets: list[RawMarketData] = Field(default_factory=list)
    relation_sets: list[LogicalRelationSetSchema] = Field(default_factory=list)
    relations: list[LogicalRelationSchema] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)


class SolverFixtureLibrary(BaseModel):
    version: str = "solver-fixtures-v1"
    fixtures: list[SolverFixtureCase] = Field(default_factory=list)


class RiskScore(BaseModel):
    oracle_risk: Probability
    deadline_risk: Probability
    semantic_risk: Probability
    execution_risk: Probability = 0.0
    liquidity_risk: Probability = 0.0
    cancellation_risk: Probability = 0.0
    source_trust_risk: Probability = 0.0
    composite: Probability
    policy_version: str = "risk-v2"

    @classmethod
    def combine(
        cls,
        oracle: float,
        deadline: float,
        semantic: float,
        execution: float = 0.0,
        liquidity: float = 0.0,
        cancellation: float = 0.0,
        source_trust: float = 0.0,
        policy_version: str = "risk-v2",
    ) -> "RiskScore":
        components = [
            oracle,
            deadline,
            semantic,
            execution,
            liquidity,
            cancellation,
            source_trust,
        ]
        return cls(
            oracle_risk=oracle,
            deadline_risk=deadline,
            semantic_risk=semantic,
            execution_risk=execution,
            liquidity_risk=liquidity,
            cancellation_risk=cancellation,
            source_trust_risk=source_trust,
            composite=round(sum(components) / len(components), 4),
            policy_version=policy_version,
        )

    @staticmethod
    def adjust_from_simulation(base: "RiskScore", simulation: "SimulationResult") -> "RiskScore":
        if simulation.execution_model != "snapshot_based":
            return base
        execution_risk = base.execution_risk
        if simulation.depth_support is True:
            execution_risk = round(max(0.0, execution_risk - 0.08), 4)
        elif simulation.depth_support is False:
            execution_risk = round(min(1.0, execution_risk + 0.30), 4)
        liquidity_risk = base.liquidity_risk
        if simulation.partial_fill_risk > 0:
            liquidity_risk = round(max(base.liquidity_risk, simulation.partial_fill_risk * 0.8), 4)
        return RiskScore.combine(
            oracle=base.oracle_risk,
            deadline=base.deadline_risk,
            semantic=base.semantic_risk,
            execution=execution_risk,
            liquidity=liquidity_risk,
            cancellation=base.cancellation_risk,
            source_trust=base.source_trust_risk,
            policy_version="risk-v2-snapshot",
        )


class SimulationResult(BaseModel):
    candidate_id: str
    displayed_edge: float = 0.0
    executable_edge: float = 0.0
    simulated_pnl: float       # post-friction estimate
    friction_bps: NonNegativeBps
    fill_probability: Probability    # heuristic execution probability estimate
    is_executable: bool        # True if simulated_pnl > 0 after execution drag
    note: str                  # short explanation of the execution model used
    estimated_slippage_bps: NonNegativeBps = 0
    estimated_slippage_cost: float = 0.0
    spread_cross_cost: float = 0.0
    stale_quote_cost: float = 0.0
    partial_fill_cost: float = 0.0
    non_execution_cost: float = 0.0
    execution_quality: Literal["high", "medium", "low"] = "medium"
    risk_flags: list[str] = Field(default_factory=list)
    venue_breakdown: dict[str, object] = Field(default_factory=dict)
    model_version: str = "heuristic-v3"
    # Snapshot-based execution fields (defaults keep backward compat with existing snapshots)
    execution_model: Literal[
        "heuristic",
        "snapshot_based",
        "replay_based",
        "degraded",
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] = "heuristic"
    execution_path: Literal[
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] = "calibrated_model"
    quote_staleness_seconds: float | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    depth_support: bool | None = None
    partial_fill_risk: float = 0.0
    execution_evidence: ExecutionEvidence | None = None


class DecisionGate(BaseModel):
    name: str
    status: Literal["pass", "watchlist", "reject", "info"]
    observed: str
    threshold: str | None = None
    detail: str | None = None


class CourtAssessment(BaseModel):
    decision: CourtDecision
    simulated_pnl: float
    fill_probability: Probability
    composite_risk: Probability | None = None
    reasons: list[str]
    opportunity_type: OpportunityType | None = None
    relation_type: RelationType | None = None
    risk_flags: list[str] = Field(default_factory=list)
    gates: list[DecisionGate] = Field(default_factory=list)
    policy_version: str = "court-v2"
    decision_path: Literal[
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] = "calibrated_model"
    evidence_packet: EvidencePacket | None = None


class RelationEvidenceResponse(BaseModel):
    from_market_id: str
    to_market_id: str
    relation_type: RelationType
    is_confirmed: bool = True
    confidence: Probability
    created_by: str
    evidence_version: str = "relation-analysis-v1"
    abstention_reason: str | None = None
    structural_relation_type: str | None = None
    semantic_relation_type: str | None = None
    semantic_confidence: Probability | None = None
    semantic_reasoning: str | None = None
    comparison_axes: list[str] = Field(default_factory=list)
    breaking_scenarios: list[Counterexample] = Field(default_factory=list)
    oracle_alignment: str | None = None
    deadline_alignment: str | None = None
    source_alignment: str | None = None
    ambiguity_terms: list[str] = Field(default_factory=list)
    relation_signals: dict[str, object] = Field(default_factory=dict)
    identity_provenance: dict[str, object] | None = None
    identity_status: IdentityResolutionStatus = IdentityResolutionStatus.UNRESOLVED
    identity_confidence: Probability | None = None
    identity_version: str = "identity-v2"
    identity_blocking_reason: str | None = None
    proof_status: str = "verified"
    tradeable_relation: bool = False
    frame_id: str | None = None
    set_key: str | None = None
    member_market_ids: list[str] = Field(default_factory=list)
    relation_proof: RelationProof | None = None


class ResolutionType(str, Enum):
    CORRECT = "CORRECT"
    IDENTITY_ERROR = "IDENTITY_ERROR"       # relation was wrongly detected
    ORACLE_DIVERGENCE = "ORACLE_DIVERGENCE" # oracle resolved unexpectedly
    CANCELLED = "CANCELLED"                 # market voided / no contest


class AutopsyLabel(str, Enum):
    FALSE_EQUIVALENCE = "false_equivalence"
    ORACLE_MISMATCH = "oracle_mismatch"
    DEADLINE_MISMATCH = "deadline_mismatch"
    AMBIGUITY_MISS = "ambiguity_miss"
    EXECUTION_MISS = "execution_miss"
    STALE_QUOTE_MISS = "stale_quote_miss"


# --- API response schemas ---

class CandidateSummary(BaseModel):
    id: str
    opportunity_type: OpportunityType
    worst_case_payoff: float
    total_cost: float
    court_decision: CourtDecision
    created_at: datetime
    execution_model: Literal[
        "heuristic",
        "snapshot_based",
        "replay_based",
        "degraded",
        "primary_proof_based",
        "calibrated_model",
        "degraded_fallback",
        "offline_validation",
    ] | None = None


class DecisionSnapshot(BaseModel):
    candidate_id: str
    run_id: str | None = None
    risk_score: RiskScore | None = None
    relation_evidence: RelationEvidenceResponse | None = None
    simulation_result: SimulationResult | None = None
    court_assessment: CourtAssessment | None = None
    decision_ledger_entry: DecisionLedgerEntry | None = None
    snapshot_version: str = "decision-snapshot-v1"
    evaluated_at: datetime


class CandidateDetail(BaseModel):
    id: str
    opportunity_type: OpportunityType
    market_ids: list[str]
    payoff_matrix: PayoffMatrix
    scenario_matrix: OutcomeStateSpace | None = None
    proof_object: ProofObject | None = None
    basket: dict[str, object] | None = None
    false_arbitrage_label: str | None = None
    risk_score: RiskScore | None
    decision_snapshot: DecisionSnapshot | None = None
    simulation_result: SimulationResult | None
    court_assessment: CourtAssessment | None = None
    relation_evidence: RelationEvidenceResponse | None = None
    court_decision: CourtDecision
    created_at: datetime


class TradeProofCertificateStatus(str, Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    INVALIDATED = "invalidated"
    SUPERSEDED = "superseded"


class TradeProofCertificate(BaseModel):
    certificate_id: str
    candidate_id: str
    run_id: str | None = None
    generated_at: datetime
    certificate_version: str = "trade-proof-certificate-v1"
    certificate_status: TradeProofCertificateStatus
    market_data_snapshot_hash: str | None = None
    compiled_contract_versions: list[str] = Field(default_factory=list)
    contract_fingerprints: dict[str, str] = Field(default_factory=dict)
    identity_evidence_ids: list[str] = Field(default_factory=list)
    identity_status: IdentityResolutionStatus
    identity_confidence: float | None = None
    identity_provenance: dict[str, object] = Field(default_factory=dict)
    identity_cluster_ids: list[str] = Field(default_factory=list)
    relation_proof_ids: list[str] = Field(default_factory=list)
    relation_set_ids: list[str] = Field(default_factory=list)
    solver_proof_object_hash: str
    payoff_matrix_hash: str
    scenario_matrix_hash: str
    orderbook_snapshot_ids: list[str] = Field(default_factory=list)
    execution_model: str = "heuristic"
    execution_simulation_hash: str | None = None
    court_decision_snapshot_id: str | None = None
    risk_score_version: str | None = None
    policy_version: str | None = None
    config_fingerprint: str | None = None
    provider_fingerprints: dict[str, str] = Field(default_factory=dict)
    invalidation_conditions: list[str] = Field(default_factory=list)
    invalidation_reason: str | None = None
    created_at: datetime
    supersedes_certificate_id: str | None = None
    degraded: bool = False


class CalibrationRunReport(BaseModel):
    calibration_run_id: str
    status: str
    sample_size: int
    input_window_start: datetime | None = None
    input_window_end: datetime | None = None
    generated_at: datetime
    active_policy_version: str | None = None
    edge_capture: float | None = None
    win_rate: float | None = None
    false_positive_rate: float | None = None
    identity_failure_rate: float | None = None
    execution_miss_rate: float | None = None
    oracle_divergence_rate: float | None = None
    opportunity_type_performance: dict[str, float] = Field(default_factory=dict)


class ActivePolicyVersionReport(BaseModel):
    policy_version: str
    status: str
    provenance: dict[str, object] = Field(default_factory=dict)
    court_thresholds: dict[str, float] = Field(default_factory=dict)
    risk_weights: dict[str, float] = Field(default_factory=dict)
    solver_penalties: dict[str, float] = Field(default_factory=dict)
    execution_calibration: dict[str, float] = Field(default_factory=dict)
    created_at: datetime


class MarketSummary(BaseModel):
    id: str
    platform: str
    title: str
    outcome_prices: list[float]
    group_id: str | None
    deadline: datetime
    deadline_precision: Literal["exact", "inferred"] = "exact"
    data_provenance: Literal["persisted"] = "persisted"
    is_closed: bool

class MarketDetail(MarketSummary):
    description: str
    resolution_criteria: str
    resolution_source: str | None
    deadline_source: str | None = None
    contract: ContractSchema | None


class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    entity_id: str | None
    payload: dict
    created_at: datetime


class PositionSummary(BaseModel):
    id: str
    candidate_id: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    actual_pnl: float | None


class PositionDetail(PositionSummary):
    legs: list[Leg]


class AutopsyRecordResponse(BaseModel):
    id: str
    candidate_id: str
    position_id: str | None
    actual_resolution: dict[str, str]
    resolution_type: ResolutionType
    identity_error: bool
    labels: list[AutopsyLabel] = Field(default_factory=list)
    created_at: datetime


class SettlementRequest(BaseModel):
    actual_pnl: float
    actual_resolution: dict[str, str]
    resolution_type: ResolutionType
    labels: list[AutopsyLabel] = Field(default_factory=list)

    @field_validator("actual_pnl")
    @classmethod
    def validate_actual_pnl(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("actual_pnl must be finite")
        if value < -1.0 or value > 1.0:
            raise ValueError("actual_pnl must be between -1.0 and 1.0")
        return value

    @field_validator("actual_resolution")
    @classmethod
    def validate_actual_resolution_values(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"YES", "NO", "N/A", "AMBIGUOUS", "CANCELLED"}
        cleaned: dict[str, str] = {}
        for market_id, resolution in value.items():
            market_key = market_id.strip()
            normalized = resolution.strip().upper()
            if not market_key:
                raise ValueError("actual_resolution keys must be non-empty")
            if normalized not in allowed:
                raise ValueError(f"unsupported actual_resolution value: {resolution}")
            cleaned[market_key] = normalized
        return cleaned

    @model_validator(mode="after")
    def validate_non_empty_resolution(self) -> "SettlementRequest":
        if not self.actual_resolution:
            raise ValueError("actual_resolution must not be empty")
        return self
