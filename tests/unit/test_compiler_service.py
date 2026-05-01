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
        session.add.assert_called_once()
        assert result == contract

    @pytest.mark.anyio
    async def test_compile_skips_recently_compiled(self):
        existing = MagicMock()
        existing.contract_json = _contract().model_dump()
        svc, session, provider = self._make_svc(existing_contract=existing)
        provider.compile = AsyncMock()

        result = await svc.compile(_market())

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

        session.add.assert_called_once()

    def test_get_recent_contract_returns_none_for_new_market(self):
        session = MagicMock()
        provider = MagicMock()
        session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        svc = CompilerService(session, provider)
        result = svc._get_recent_contract("pm:a")
        assert result is None
