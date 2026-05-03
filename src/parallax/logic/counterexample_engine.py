from __future__ import annotations

from itertools import combinations

from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import ContractSchema, Counterexample, RelationType


class CounterexampleEngine:
    def collect(
        self,
        *,
        relation_type: RelationType,
        contract_a: ContractSchema,
        contract_b: ContractSchema,
        classification: RelationClassification | None = None,
    ) -> list[Counterexample]:
        explicit = list(classification.breaking_scenarios) if classification is not None else []
        if explicit:
            return explicit

        generated: list[Counterexample] = []
        if contract_a.temporal_deadline and contract_b.temporal_deadline and contract_a.temporal_deadline != contract_b.temporal_deadline:
            generated.append(
                Counterexample(
                    scenario_description="Markets cross different deadlines.",
                    resolution_a="YES",
                    resolution_b="NO",
                    why_different="deadline mismatch changes the resolution window",
                )
            )
        if contract_a.oracle_scope and contract_b.oracle_scope and contract_a.oracle_scope != contract_b.oracle_scope:
            generated.append(
                Counterexample(
                    scenario_description="Markets rely on different oracles.",
                    resolution_a="YES",
                    resolution_b="AMBIGUOUS",
                    why_different="oracle mismatch can produce non-fungible settlements",
                )
            )
        if relation_type in {RelationType.EQUIVALENT, RelationType.DUPLICATE} and generated:
            return generated
        if relation_type in {RelationType.SUBSET, RelationType.SUPERSET} and generated:
            return generated
        return generated

    def collect_partition(
        self,
        *,
        contracts: list[ContractSchema],
        pair_reviews: list[dict[str, object]] | None = None,
    ) -> list[Counterexample]:
        explicit: list[Counterexample] = []
        for review in pair_reviews or []:
            for scenario in review.get("breaking_scenarios", []):
                explicit.append(Counterexample.model_validate(scenario))
        if explicit:
            return explicit

        generated: list[Counterexample] = []
        for contract_a, contract_b in combinations(contracts, 2):
            generated.extend(
                self.collect(
                    relation_type=RelationType.EXHAUSTIVE_PARTITION,
                    contract_a=contract_a,
                    contract_b=contract_b,
                    classification=None,
                )
            )

        deduped: list[Counterexample] = []
        seen: set[tuple[str, str, str, str]] = set()
        for record in generated:
            key = (
                record.scenario_description,
                record.resolution_a,
                record.resolution_b,
                record.why_different,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        return deduped
