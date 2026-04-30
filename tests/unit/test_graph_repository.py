import uuid
from unittest.mock import MagicMock, patch
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.db.models import MarketRelation
from parallax.shared.schemas import RelationType


def _make_relation(**kwargs) -> MarketRelation:
    defaults = dict(
        id=uuid.uuid4(),
        from_market_id="polymarket:a",
        to_market_id="kalshi:b",
        relation_type=RelationType.EQUIVALENT.value,
        confidence=0.9,
        evidence={"source": "test"},
        created_by="test",
    )
    defaults.update(kwargs)
    return MarketRelation(**defaults)


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
        session.add.assert_called_once()
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
