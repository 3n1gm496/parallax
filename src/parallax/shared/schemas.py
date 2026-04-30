from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class RelationType(str, Enum):
    EQUIVALENT = "equivalent"
    DUPLICATE = "duplicate"
    SUBSET = "subset"
    SUPERSET = "superset"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    EXHAUSTIVE = "exhaustive"
    PREREQUISITE = "prerequisite"
    INVERSE = "inverse"
    SAME_EVENT_DIFFERENT_DEADLINE = "same_event_different_deadline"
    SAME_EVENT_DIFFERENT_ORACLE = "same_event_different_oracle"
    SAME_EVENT_DIFFERENT_SOURCE = "same_event_different_source"
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
    PENDING = "PENDING"
    PAPER_TRADE = "PAPER_TRADE"
    CANDIDATE_FOR_LIVE = "CANDIDATE_FOR_LIVE"


class RawMarketData(BaseModel):
    platform: str
    market_id: str
    title: str
    description: str
    resolution_criteria: str
    outcomes: list[str]
    outcome_prices: list[float]
    category: str | None = None
    group_id: str | None = None   # Polymarket event ID — used for Stage 1 grouping
    deadline: datetime
    is_closed: bool
    resolution_source: str | None = None
    raw_payload: dict


class AmbiguityFlag(BaseModel):
    term: str
    description: str


class Counterexample(BaseModel):
    scenario_description: str
    resolution_a: str   # "YES" | "NO" | "AMBIGUOUS"
    resolution_b: str
    why_different: str


class ContractSchema(BaseModel):
    yes_conditions: list[str]
    no_conditions: list[str]
    exclusions: list[str]
    ambiguity_terms: list[AmbiguityFlag]
    counterexamples: list[Counterexample]
    compiler_confidence: float   # 0.0–1.0; calibrated over time


class Leg(BaseModel):
    market_id: str
    side: str = "YES"            # "YES" | "NO"
    price: float
    quantity: float = 1.0
    cost: float | None = None    # defaults to price * quantity; set explicitly when known
    outcome: str | None = None   # human-readable outcome label, e.g. "Biden wins"
    platform: str | None = None


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
    friction_bps: int


class RiskScore(BaseModel):
    oracle_risk: float
    deadline_risk: float
    semantic_risk: float
    composite: float

    @classmethod
    def combine(cls, oracle: float, deadline: float, semantic: float) -> "RiskScore":
        return cls(
            oracle_risk=oracle,
            deadline_risk=deadline,
            semantic_risk=semantic,
            composite=round((oracle + deadline + semantic) / 3, 4),
        )


class SimulationResult(BaseModel):
    candidate_id: str
    simulated_pnl: float       # post-friction estimate
    friction_bps: int
    fill_probability: float    # 1.0 in stub (assumes full fill)
    is_executable: bool        # True if simulated_pnl > 0
    note: str                  # "stub — no order book model" in Slice 1


class ResolutionType(str, Enum):
    CORRECT = "CORRECT"
    IDENTITY_ERROR = "IDENTITY_ERROR"       # relation was wrongly detected
    ORACLE_DIVERGENCE = "ORACLE_DIVERGENCE" # oracle resolved unexpectedly
    CANCELLED = "CANCELLED"                 # market voided / no contest


# --- API response schemas ---

class CandidateSummary(BaseModel):
    id: str
    opportunity_type: str
    worst_case_payoff: float
    total_cost: float
    court_decision: str
    created_at: datetime

class CandidateDetail(BaseModel):
    id: str
    opportunity_type: str
    market_ids: list[str]
    payoff_matrix: PayoffMatrix
    risk_score: RiskScore | None
    simulation_result: SimulationResult | None
    court_decision: str
    created_at: datetime

class MarketSummary(BaseModel):
    id: str
    platform: str
    title: str
    outcome_prices: list[float]
    group_id: str | None
    deadline: datetime
    is_closed: bool

class MarketDetail(MarketSummary):
    description: str
    resolution_criteria: str
    resolution_source: str | None
    contract: ContractSchema | None

class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    entity_id: str | None
    payload: dict
    created_at: datetime

class RunSummary(BaseModel):
    markets_ingested: int
    contracts_compiled: int
    events_resolved: int
    relations_detected: int
    candidates_found: int
    candidates_watchlisted: int
    errors: list[str]
