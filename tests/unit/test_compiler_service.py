from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest
from parallax.compiler.service import CompilerService
from parallax.shared.schemas import ContractSchema


def _contract() -> ContractSchema:
    return ContractSchema(
        yes_conditions=["X happens"],
        no_conditions=["X does not happen"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.85,
    )


def _market(mid: str = "pm:a") -> MagicMock:
    m = MagicMock()
    m.id = mid
    m.platform = "polymarket"
    m.title = "Will X happen?"
    m.description = "Resolves YES if X."
    m.resolution_criteria = "Resolves YES if X; NO otherwise."
    m.outcomes = ["Yes", "No"]
    m.outcome_prices = [0.6, 0.4]
    m.deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
    m.is_closed = False
    m.raw_payload = {}
    m.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return m


class TestCompilerService:
    def _make_svc(self, existing_contract=None):
        session = MagicMock()
        provider = MagicMock()
        provider.version = "anthropic-sonnet-4-6-v1"
        svc = CompilerService(session, provider)
        svc._get_recent_contract = MagicMock(return_value=existing_contract)
        return svc, session, provider

    @pytest.mark.anyio
    async def test_compile_new_market_stores_contract(self):
        svc, session, provider = self._make_svc(existing_contract=None)
        contract = _contract()
        provider.compile = AsyncMock(return_value=contract)

        result = await svc.compile(_market())

        provider.compile.assert_called_once()
        assert session.add.called
        assert result.yes_conditions == contract.yes_conditions
        assert result.canonical_subject is not None
        assert result.proposition_family is not None

    @pytest.mark.anyio
    async def test_compile_skips_recently_compiled(self):
        existing = MagicMock()
        existing.contract_json = _contract().model_dump()
        existing.compiler_version = "anthropic-sonnet-4-6-v1"
        existing.compiled_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        svc, session, provider = self._make_svc(existing_contract=existing)
        provider.compile = AsyncMock()
        market = _market()
        market.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        result = await svc.compile(market)

        provider.compile.assert_not_called()
        session.add.assert_not_called()
        assert result.yes_conditions == ["X happens"]

    @pytest.mark.anyio
    async def test_compile_low_confidence_still_stores(self):
        svc, session, provider = self._make_svc(existing_contract=None)
        low_conf = _contract()
        low_conf = low_conf.model_copy(update={"compiler_confidence": 0.3})
        provider.compile = AsyncMock(return_value=low_conf)

        await svc.compile(_market())

        assert session.add.called

    def test_get_recent_contract_returns_none_for_new_market(self):
        session = MagicMock()
        provider = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        svc = CompilerService(session, provider)
        result = svc._get_recent_contract("pm:a")
        assert result is None

    @pytest.mark.anyio
    async def test_compile_recompiles_when_market_changed_after_cached_contract(self):
        existing = MagicMock()
        existing.contract_json = _contract().model_dump()
        existing.compiler_version = "anthropic-sonnet-4-6-v1"
        existing.compiled_at = datetime(2024, 12, 31, tzinfo=timezone.utc)
        svc, session, provider = self._make_svc(existing_contract=existing)
        provider.compile = AsyncMock(return_value=_contract())

        await svc.compile(_market())

        provider.compile.assert_called_once()

    @pytest.mark.anyio
    async def test_compile_recompiles_when_provider_version_changes(self):
        existing = MagicMock()
        existing.contract_json = _contract().model_dump()
        existing.compiler_version = "older-version"
        existing.compiled_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
        svc, session, provider = self._make_svc(existing_contract=existing)
        provider.compile = AsyncMock(return_value=_contract())
        market = _market()
        market.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        await svc.compile(market)

        provider.compile.assert_called_once()
