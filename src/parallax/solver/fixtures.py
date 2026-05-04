from __future__ import annotations

from datetime import datetime, timezone

from parallax.shared.schemas import (
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    RawMarketData,
    RelationType,
    SolverFixtureCase,
    SolverFixtureLibrary,
)


def build_fixture_library() -> SolverFixtureLibrary:
    deadline = datetime(2026, 12, 31, tzinfo=timezone.utc)
    fixture_markets = lambda items: [
        RawMarketData(
            platform=platform,
            market_id=market_id,
            title=title,
            description="fixture",
            resolution_criteria="fixture",
            outcomes=["Yes", "No"],
            outcome_prices=[price, 1 - price],
            deadline=deadline,
            is_closed=False,
            raw_payload={},
        )
        for platform, market_id, title, price in items
    ]
    return SolverFixtureLibrary(
        fixtures=[
            SolverFixtureCase(
                case_key="equivalent-2-leg",
                description="duplicate/equivalent spread",
                relation_type=RelationType.EQUIVALENT,
                markets=fixture_markets([("pm", "eq-a", "eq-a", 0.40), ("kalshi", "eq-b", "eq-b", 0.55)]),
                relations=[
                    LogicalRelationSchema(
                        from_market_id="pm:eq-a",
                        to_market_id="kalshi:eq-b",
                        relation_type=RelationType.EQUIVALENT,
                        proof_status="verified",
                        tradeable_relation=True,
                        confidence=0.95,
                        created_by="fixture",
                    )
                ],
            ),
            SolverFixtureCase(
                case_key="mutex-3-leg",
                description="exhaustive 3-leg partition",
                relation_type=RelationType.EXHAUSTIVE_PARTITION,
                markets=fixture_markets([("pm", "m1", "m1", 0.40), ("pm", "m2", "m2", 0.36), ("pm", "m3", "m3", 0.35)]),
                relation_sets=[
                    LogicalRelationSetSchema(
                        set_key="pm:m1|pm:m2|pm:m3",
                        member_market_ids=["pm:m1", "pm:m2", "pm:m3"],
                        relation_type=RelationType.EXHAUSTIVE_PARTITION,
                        proof_status="verified",
                        tradeable_relation=True,
                        confidence=0.95,
                        created_by="fixture",
                    )
                ],
            ),
        ]
    )
