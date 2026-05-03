import uuid
from unittest.mock import MagicMock
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.db.models import LogicalRelation
from parallax.shared.schemas import CounterexampleRecord, RelationType


def _make_relation(**kwargs) -> LogicalRelation:
    defaults = dict(
        id=uuid.uuid4(),
        from_market_id="polymarket:a",
        to_market_id="kalshi:b",
        frame_id=None,
        relation_type=RelationType.EQUIVALENT.value,
        proof_status="verified",
        tradeable_relation=True,
        confidence=0.9,
        evidence={"source": "test"},
        created_by="test",
    )
    defaults.update(kwargs)
    return LogicalRelation(**defaults)


class TestPostgresGraphRepository:
    def test_add_relation_returns_id(self):
        session = MagicMock()
        session.flush = MagicMock()
        repo = PostgresGraphRepository(session)
        rid = repo.add_relation(
            from_market_id="polymarket:a",
            to_market_id="kalshi:b",
            relation_type=RelationType.EQUIVALENT,
            confidence=0.9,
            evidence={"src": "unit"},
            created_by="test",
        )
        assert session.add.call_count == 1
        session.flush.assert_called_once()
        assert isinstance(rid, str)
        uuid.UUID(rid)  # must be a valid UUID string

    def test_get_relations_returns_matching(self):
        session = MagicMock()
        rel = _make_relation()
        session.query.return_value.filter.return_value.all.return_value = [rel]
        repo = PostgresGraphRepository(session)
        results = repo.get_relations("polymarket:a")
        assert len(results) == 1
        assert results[0]["from_market_id"] == "polymarket:a"
        assert results[0]["to_market_id"] == "kalshi:b"

    def test_get_relations_with_type_filter(self):
        session = MagicMock()
        rel = _make_relation()
        chain = session.query.return_value.filter.return_value
        chain.filter.return_value.all.return_value = [rel]
        repo = PostgresGraphRepository(session)
        results = repo.get_relations("polymarket:a", relation_type=RelationType.EQUIVALENT)
        chain.filter.assert_called_once()
        assert len(results) == 1

    def test_relation_exists_returns_true_when_found(self):
        session = MagicMock()
        rel = _make_relation()
        session.query.return_value.filter.return_value.first.return_value = rel
        repo = PostgresGraphRepository(session)
        assert repo.relation_exists("polymarket:a", "kalshi:b", RelationType.EQUIVALENT) is True

    def test_relation_exists_returns_false_when_not_found(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        repo = PostgresGraphRepository(session)
        assert repo.relation_exists("polymarket:a", "kalshi:b", RelationType.EQUIVALENT) is False

    def test_relation_exists_checks_reverse_direction(self):
        """relation_exists must find (b→a) even when queried as (a→b)."""
        session = MagicMock()
        rel = _make_relation(from_market_id="kalshi:b", to_market_id="polymarket:a")
        session.query.return_value.filter.return_value.first.return_value = rel
        repo = PostgresGraphRepository(session)
        # Query with original direction — should still find the reversed record
        assert repo.relation_exists("polymarket:a", "kalshi:b", RelationType.EQUIVALENT) is True

    def test_delete_relation_returns_true_when_found(self):
        session = MagicMock()
        rel = _make_relation()
        relation_id = str(rel.id)
        session.get.return_value = rel
        session.query.return_value.filter.return_value.first.return_value = None
        repo = PostgresGraphRepository(session)
        result = repo.delete_relation(relation_id)
        assert result is True
        session.delete.assert_called_once_with(rel)
        session.flush.assert_called_once()

    def test_delete_relation_returns_false_when_not_found(self):
        session = MagicMock()
        session.get.return_value = None
        repo = PostgresGraphRepository(session)
        result = repo.delete_relation(str(uuid.uuid4()))
        assert result is False
        session.delete.assert_not_called()

    def test_add_counterexample_record_returns_id(self):
        session = MagicMock()
        session.flush = MagicMock()
        repo = PostgresGraphRepository(session)
        record_id = repo.add_counterexample_record(
            CounterexampleRecord(
                relation_type=RelationType.EQUIVALENT,
                scenario_description="deadline mismatch",
                resolution_a="YES",
                resolution_b="NO",
                why_different="different deadlines",
                source="unit",
                created_by="unit",
            )
        )
        assert session.add.called
        session.flush.assert_called_once()
        uuid.UUID(record_id)

    def test_add_relation_set_returns_id(self):
        session = MagicMock()
        session.flush = MagicMock()
        repo = PostgresGraphRepository(session)
        relation_set_id = repo.add_relation_set(
            set_key="pm:a|pm:b|pm:c",
            member_market_ids=["pm:a", "pm:b", "pm:c"],
            relation_type=RelationType.EXHAUSTIVE_PARTITION,
            confidence=0.81,
            evidence={"frame_id": "frame-1", "proof_status": "verified", "tradeable_relation": True},
            created_by="semantic_relation_analyzer",
        )
        assert session.add.called
        session.flush.assert_called_once()
        uuid.UUID(relation_set_id)

    def test_get_relation_set_returns_matching(self):
        session = MagicMock()
        row = MagicMock(
            id=uuid.uuid4(),
            set_key="pm:a|pm:b|pm:c",
            frame_id=None,
            member_market_ids=["pm:a", "pm:b", "pm:c"],
            relation_type=RelationType.EXHAUSTIVE_PARTITION.value,
            proof_status="verified",
            tradeable_relation=True,
            confidence=0.8,
            evidence={"proof_status": "verified"},
            created_by="test",
        )
        session.query.return_value.filter.return_value.first.return_value = row
        repo = PostgresGraphRepository(session)
        result = repo.get_relation_set("pm:a|pm:b|pm:c")
        assert result is not None
        assert result["set_key"] == "pm:a|pm:b|pm:c"

    def test_list_relation_sets_returns_rows(self):
        session = MagicMock()
        row = MagicMock(
            id=uuid.uuid4(),
            set_key="pm:a|pm:b|pm:c",
            frame_id=None,
            member_market_ids=["pm:a", "pm:b", "pm:c"],
            relation_type=RelationType.EXHAUSTIVE_PARTITION.value,
            proof_status="verified",
            tradeable_relation=True,
            confidence=0.8,
            evidence={"proof_status": "verified"},
            created_by="test",
        )
        session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [row]
        repo = PostgresGraphRepository(session)
        result = repo.list_relation_sets(limit=10)
        assert len(result) == 1
        assert result[0]["relation_type"] == RelationType.EXHAUSTIVE_PARTITION.value
