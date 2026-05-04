from __future__ import annotations

from itertools import product

from parallax.shared.schemas import OutcomeState, OutcomeStateSpace, RelationType, ScenarioConstraintModel


class OutcomeStateSpaceBuilder:
    def enumerate(
        self,
        *,
        market_ids: list[str],
        constraints: list[ScenarioConstraintModel],
    ) -> OutcomeStateSpace:
        valid_states: list[OutcomeState] = []
        impossible_states: list[OutcomeState] = []

        for idx, values in enumerate(product(("YES", "NO"), repeat=len(market_ids))):
            assignments = dict(zip(market_ids, values, strict=True))
            violated = [
                constraint.constraint_key
                for constraint in constraints
                if not self._satisfies(assignments, constraint)
            ]
            state = OutcomeState(
                state_id=f"state-{idx}",
                assignments=assignments,
                is_possible=not violated,
                violated_constraints=violated,
                explanation=None if not violated else f"violates {', '.join(violated)}",
            )
            if violated:
                impossible_states.append(state)
            else:
                valid_states.append(state)

        return OutcomeStateSpace(
            market_ids=market_ids,
            valid_states=valid_states,
            impossible_states=impossible_states,
            enumeration_mode="custom",
        )

    def _satisfies(self, assignments: dict[str, str], constraint: ScenarioConstraintModel) -> bool:
        ids = [market_id for market_id in constraint.market_ids if market_id in assignments]
        if len(ids) < 2:
            return True

        yes_count = sum(1 for market_id in ids if assignments[market_id] == "YES")
        first = assignments[ids[0]]
        second = assignments[ids[1]]
        relation = constraint.relation_type

        if relation in {RelationType.EQUIVALENT, RelationType.DUPLICATE}:
            return all(assignments[market_id] == first for market_id in ids)
        if relation == RelationType.MUTUALLY_EXCLUSIVE:
            return yes_count <= 1
        if relation in {RelationType.EXHAUSTIVE, RelationType.EXHAUSTIVE_PARTITION}:
            return yes_count == 1
        if relation in {RelationType.SUBSET, RelationType.PREREQUISITE}:
            return not (first == "YES" and second == "NO")
        if relation == RelationType.SUPERSET:
            return not (first == "NO" and second == "YES")
        if relation == RelationType.INVERSE:
            return first != second
        return True
