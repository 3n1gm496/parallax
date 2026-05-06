from unittest.mock import MagicMock
import uuid
from parallax.audit.repository import AuditRepository
from parallax.audit.service import AuditService
from parallax.db.models import AuditEvent


def _make_event(**kwargs) -> AuditEvent:
    defaults = dict(
        id=uuid.uuid4(),
        event_type="test.event",
        entity_type="candidate",
        entity_id="abc",
        payload={},
    )
    defaults.update(kwargs)
    return AuditEvent(**defaults)


class TestAuditRepository:
    def test_append_adds_and_returns_event(self):
        session = MagicMock()
        repo = AuditRepository(session)

        event = repo.append("market.ingested", "market", "m:1", {"foo": "bar"})

        assert event.event_type == "market.ingested"
        assert event.entity_type == "market"
        assert event.entity_id == "m:1"
        assert event.payload == {"foo": "bar"}
        session.add.assert_called_once_with(event)

    def test_append_assigns_uuid(self):
        session = MagicMock()
        repo = AuditRepository(session)
        event = repo.append("x", "y", "z", {})
        assert event.id is not None

    def test_append_does_not_expose_update_or_delete(self):
        repo = AuditRepository(MagicMock())
        assert not hasattr(repo, "update")
        assert not hasattr(repo, "delete")

    def test_list_for_entity_queries_correctly(self):
        session = MagicMock()
        expected = [_make_event()]
        (
            session.query.return_value
            .filter_by.return_value
            .order_by.return_value
            .all.return_value
        ) = expected

        repo = AuditRepository(session)
        result = repo.list_for_entity("candidate", "abc")

        session.query.assert_called_once_with(AuditEvent)
        assert result == expected

    def test_list_recent_applies_limit(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        repo = AuditRepository(session)
        repo.list_recent(limit=50)
        session.query.return_value.order_by.return_value.limit.assert_called_once_with(50)


class TestAuditService:
    def test_record_flushes_session(self):
        session = MagicMock()
        # Make the chain return a valid AuditEvent-like mock
        session.add = MagicMock()
        session.flush = MagicMock()

        svc = AuditService(session)
        event = svc.record("candidate.approved", "candidate", "c:1", {"decision": "APPROVED"})

        session.flush.assert_called_once()
        assert event.event_type == "candidate.approved"

    def test_get_history_delegates_to_repo(self):
        session = MagicMock()
        expected = [_make_event()]
        (
            session.query.return_value
            .filter_by.return_value
            .order_by.return_value
            .all.return_value
        ) = expected

        svc = AuditService(session)
        result = svc.get_history("candidate", "c:1")
        assert result == expected

    def test_get_recent_delegates_to_repo(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        svc = AuditService(session)
        svc.get_recent(limit=10)
        session.query.return_value.order_by.return_value.limit.assert_called_once_with(10)
