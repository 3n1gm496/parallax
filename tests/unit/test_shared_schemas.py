def test_contract_schema_requires_confidence():
    from parallax.shared.schemas import ContractSchema
    s = ContractSchema(
        yes_conditions=["Trump wins electoral college"],
        no_conditions=["Trump does not win"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.85,
    )
    assert s.compiler_confidence == 0.85

def test_payoff_matrix_worst_case():
    from parallax.shared.schemas import PayoffMatrix, Leg, Scenario, OpportunityType
    leg = Leg(market_id="m1", side="YES", price=0.40, quantity=1.0, outcome="Biden wins", platform="polymarket")
    breaking = Scenario(name="break", description="markets diverge", is_breaking=True, payoff=-0.40)
    good = Scenario(name="win", description="all YES", is_breaking=False, payoff=0.58)
    pm = PayoffMatrix(
        legs=[leg],
        total_cost=0.40,
        scenarios=[breaking, good],
        worst_case_payoff=-0.40,
        best_case_payoff=0.58,
        breaking_scenario=breaking,
        opportunity_type=OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING,
        friction_bps=50,
    )
    assert pm.worst_case_payoff == -0.40
