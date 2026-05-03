import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock
from parallax.identity.event_repository import EventRepository
from parallax.identity.service import IdentityService
from parallax.db.models import CanonicalEvent, MarketEventLink, RawMarket
from parallax.shared.schemas import IdentityResolutionStatus


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


def _make_market(**kwargs) -> RawMarket:
    defaults = dict(
        id=f"market-{uuid.uuid4()}",
        platform="polymarket",
        market_id=uuid.uuid4().hex[:8],
        title="Will inflation rise in 2026?",
        description="desc",
        resolution_criteria="criteria",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        category="macro",
        group_id=None,
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source="fed",
        raw_payload={},
    )
    defaults.update(kwargs)
    return RawMarket(**defaults)


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

        from unittest.mock import patch
        with patch("parallax.identity.service.AuditService") as MockAudit:
            svc = IdentityService(session)
            event, created = svc.get_or_create_event("New event", "crypto", "g-new")

        assert created is True
        assert event.name == "New event"
        session.add.assert_called()
        session.flush.assert_called()
        MockAudit.return_value.record.assert_called_once()

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

        from unittest.mock import patch
        with patch("parallax.identity.service.AuditService") as MockAudit:
            svc = IdentityService(session)
            event_id = uuid.uuid4()
            link = svc.link_market(
                "polymarket:abc",
                event_id,
                link_reason="multi_signal_match",
                provenance={"score": 0.88},
            )

        assert link is not None
        assert link.raw_market_id == "polymarket:abc"
        assert link.canonical_event_id == event_id
        assert link.link_reason == "multi_signal_match"
        assert link.provenance == {"score": 0.88}
        session.add.assert_called_with(link)
        MockAudit.return_value.record.assert_called_once()

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

    def test_resolve_all_ungrouped_links_grouped_open_markets(self):
        session = MagicMock()
        session.query.return_value.filter_by.return_value.first.return_value = None
        session.get.return_value = None
        session.flush = MagicMock()
        from unittest.mock import patch
        with patch("parallax.identity.service.AuditService") as MockAudit:
            svc = IdentityService(session)

            market = MagicMock(
                id="polymarket:abc",
                platform="polymarket",
                group_id="g1",
                title="Will X happen?",
                category="politics",
            )
            svc._market_repo.list_unlinked_open = MagicMock(return_value=[market])

            count = svc.resolve_all_ungrouped()

        assert count == 1
        assert MockAudit.return_value.record.call_count >= 3

    def test_compare_market_pair_returns_linkable_multi_signal_match(self):
        session = MagicMock()
        svc = IdentityService(session)
        market = _make_market(title="Will US inflation rise in 2026?")
        linked_market = _make_market(
            id="kalshi:inflation-2026",
            platform="kalshi",
            market_id="inflation-2026",
            title="US inflation rise in 2026?",
        )

        result = svc._compare_market_pair(market, linked_market)

        assert result["decision"] == "linked"
        assert result["lexical_similarity"] >= 0.55
        assert result["normalized_time_compatible"] is True

    def test_match_existing_event_stays_conservative_when_two_events_tie(self):
        session = MagicMock()
        svc = IdentityService(session)
        market = _make_market(title="Will inflation rise in 2026?")
        event_a = _make_event()
        event_b = _make_event()
        shared_match = _make_market(title="US inflation rise in 2026?")

        svc._repo.list_active = MagicMock(return_value=[event_a, event_b])
        svc._repo.list_markets_for_event = MagicMock(return_value=[shared_match])

        result = svc._match_existing_event(market, domain="macro")

        assert result["selected_event"] is None
        assert result["status"] == IdentityResolutionStatus.AMBIGUOUS

    def test_match_existing_event_returns_verified_choice_when_clear_winner(self):
        session = MagicMock()
        svc = IdentityService(session)
        market = _make_market(title="Will inflation rise in 2026?")
        event = _make_event()
        linked_market = _make_market(title="US inflation rise in 2026?")

        svc._repo.list_active = MagicMock(return_value=[event])
        svc._repo.list_markets_for_event = MagicMock(return_value=[linked_market])

        result = svc._match_existing_event(market, domain="macro")

        assert result["selected_event"] is event
        assert result["status"] == IdentityResolutionStatus.VERIFIED
        assert result["selected_provenance"]["identity_status"] == IdentityResolutionStatus.VERIFIED.value
