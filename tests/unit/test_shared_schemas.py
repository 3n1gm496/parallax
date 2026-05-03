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


def test_settlement_request_accepts_autopsy_labels():
    from parallax.shared.schemas import AutopsyLabel, ResolutionType, SettlementRequest

    payload = SettlementRequest(
        actual_pnl=0.05,
        actual_resolution={"pm:a": "YES"},
        resolution_type=ResolutionType.CORRECT,
        labels=[AutopsyLabel.EXECUTION_MISS],
    )

    assert payload.labels == [AutopsyLabel.EXECUTION_MISS]


def test_contract_schema_accepts_json_stringified_lists_from_llm_tooling():
    from parallax.shared.schemas import ContractSchema

    payload = {
        "yes_conditions": "[\"X happens\"]",
        "no_conditions": "[\"X does not happen\"]",
        "exclusions": "[]",
        "ambiguity_terms": "[{\"term\": \"soon\", \"description\": \"Timing is vague\"}]",
        "counterexamples": (
            "[{\"scenario_description\": \"Late cutoff\", \"resolution_a\": \"YES\", "
            "\"resolution_b\": \"NO\", \"why_different\": \"Deadlines differ\"}]"
        ),
        "compiler_confidence": 0.72,
    }

    contract = ContractSchema.model_validate(payload)

    assert contract.yes_conditions == ["X happens"]
    assert contract.ambiguity_terms[0].term == "soon"
    assert contract.counterexamples[0].resolution_b == "NO"


def test_contract_schema_syncs_blueprint_alias_fields():
    from parallax.shared.schemas import ContractSchema

    contract = ContractSchema(
        yes_conditions=["X happens"],
        no_conditions=["X does not happen"],
        exclusions=["void if cancelled"],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.8,
        comparator="greater_than",
        threshold_value="10",
        temporal_deadline="2025-12-31T00:00:00+00:00",
        oracle_focus="official",
        canonical_predicate="wins",
    )

    assert contract.threshold_comparator == "greater_than"
    assert contract.threshold == "10"
    assert contract.time_scope == "2025-12-31T00:00:00+00:00"
    assert contract.oracle_scope == "official"
    assert contract.resolution_exclusions == ["void if cancelled"]
    assert contract.polarity == "positive"
