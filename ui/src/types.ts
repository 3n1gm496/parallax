export interface Leg {
  market_id: string;
  side: "YES" | "NO";
  price: number;
  quantity: number;
  cost: number | null;
  outcome: string | null;
  platform: string | null;
}

export interface Scenario {
  name: string;
  description: string;
  is_breaking: boolean;
  payoff: number;
}

export interface PayoffMatrix {
  legs: Leg[];
  total_cost: number;
  scenarios: Scenario[];
  worst_case_payoff: number;
  best_case_payoff: number;
  breaking_scenario: Scenario | null;
  opportunity_type: string;
  friction_bps: number;
}

export interface RiskScore {
  oracle_risk: number;
  deadline_risk: number;
  semantic_risk: number;
  composite: number;
}

export interface SimulationResult {
  candidate_id: string;
  simulated_pnl: number;
  friction_bps: number;
  fill_probability: number;
  is_executable: boolean;
  note: string;
}

export interface CandidateSummary {
  id: string;
  opportunity_type: string;
  worst_case_payoff: number;
  total_cost: number;
  court_decision: string;
  created_at: string;
}

export interface CandidateDetail {
  id: string;
  opportunity_type: string;
  market_ids: string[];
  payoff_matrix: PayoffMatrix;
  risk_score: RiskScore | null;
  simulation_result: SimulationResult | null;
  court_decision: string;
  created_at: string;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  entity_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}
