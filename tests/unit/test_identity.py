import uuid
from unittest.mock import MagicMock
from parallax.identity.event_repository import EventRepository
from parallax.identity.service import IdentityService
from parallax.db.models import CanonicalEvent, MarketEventLink


def _make_event(**kwargs) -> CanonicalEvent:
    defaults = dict(
        id=uuid.uuid4(),
        name="Test event",
        domain="politics",
        status="active",
        platform_group_key=None,
    )
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


class TestEventRepository:
    def test_get_delegates_to_session(self):
        session = MagicMock()
        session.get.return_value = None
        repo = EventRepository(session)
        event_id = uuid.uuid4()
        repo.get(event_id)
        session.get.assert_called_with(CanonicalEvent, event_id)

    def test_get_by_group_key_queries_correctly(self):
        session = MagicMock()
        expected = _make_event(platform_group_key="g1")
        session.query.return_value.filter_by.return_value.first.return_value = expected
        repo = EventRepository(session)
        result = repo.get_by_group_key("g1")
        assert result is expected

    def test_create_adds_event(self):
        session = MagicMock()
        repo = EventRepository(session)
        event = repo.create("US Election", "politics", "group-1")
        assert event.name == "US Election"
        assert event.domain == "politics"
        assert event.platform_group_key == "group-1"
        session.add.assert_called_once_with(event)

    def test_list_active_filters_by_status(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.all.return_value = []
        repo = EventRepository(session)
        repo.list_active()
        session.query.return_value.filter_by.assert_called_with(status="active")

    def test_list_active_with_domain(self):
        session = MagicMock()
        chain = session.query.return_value.filter_by.return_value
        chain.filter_by.return_value.all.return_value = []
        repo = EventRepository(session)
        repo.list_active(domain="politics")
        chain.filter_by.assert_called_with(domain="politics")


class TestIdentityService:
    def test_get_or_create_returns_existing_by_group_key(self):
        session = MagicMock()
        existing = _make_event(platform_group_key="g1")
        session.query.return_value.filter_by.return_value.first.return_value = existing

        svc = IdentityService(session)
        event, created = svc.get_or_create_event("Any name", "politics", "g1")

        assert created is False
        assert event is existing

    def test_get_or_create_creates_when_no_match(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.flush = MagicMock()

        svc = IdentityService(session)
        event, created = svc.get_or_create_event("New event", "crypto", "g-new")

        assert created is True
        assert event.name == "New event"
        session.add.assert_called()
        session.flush.assert_called()

    def test_get_or_create_without_group_key_always_creates(self):
        session = MagicMock()
        session.flush = MagicMock()

        svc = IdentityService(session)
        event, created = svc.get_or_create_event("Unnamed", "sports")

        assert created is True

    def test_link_market_creates_link(self):
        session = MagicMock()
        session.get.return_value = None
        session.flush = MagicMock()

        svc = IdentityService(session)
        event_id = uuid.uuid4()
        link = svc.link_market("polymarket:abc", event_id)

        assert link is not None
        assert link.raw_market_id == "polymarket:abc"
        assert link.canonical_event_id == event_id
        session.add.assert_called_with(link)

    def test_link_market_returns_none_if_already_linked(self):
        session = MagicMock()
        event_id = uuid.uuid4()
        existing_link = MarketEventLink(
            raw_market_id="polymarket:abc",
            canonical_event_id=event_id,
        )
        session.get.return_value = existing_link

        svc = IdentityService(session)
        result = svc.link_market("polymarket:abc", event_id)
        assert result is None
