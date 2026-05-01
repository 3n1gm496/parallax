from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from parallax.compiler.provider import CompilerProvider
from parallax.db.models import CompiledContract
from parallax.shared.schemas import ContractSchema, RawMarketData

_RECOMPILE_AFTER_HOURS = 24


class CompilerService:
    """Compile a RawMarket into a ContractSchema and persist as CompiledContract."""

    def __init__(self, session: Session, provider: CompilerProvider) -> None:
        self._session = session
        self._provider = provider

    async def compile(self, market) -> ContractSchema:
        existing = self._get_recent_contract(market.id)
        if existing is not None:
            return ContractSchema.model_validate(existing.contract_json)

        # Real RawMarket stores market_id as a str column; fall back to id suffix otherwise.
        _mid = market.market_id
        market_id_str = _mid if isinstance(_mid, str) else market.id.split(":")[-1]

        market_data = RawMarketData(
            platform=market.platform,
            market_id=market_id_str,
            title=market.title,
            description=market.description,
            resolution_criteria=market.resolution_criteria,
            outcomes=list(market.outcomes) if market.outcomes else [],
            outcome_prices=list(market.outcome_prices) if market.outcome_prices else [],
            deadline=market.deadline,
            is_closed=market.is_closed,
            raw_payload=dict(market.raw_payload) if market.raw_payload else {},
        )
        contract = await self._provider.compile(market_data)

        row = CompiledContract(
            id=uuid.uuid4(),
            raw_market_id=market.id,
            contract_json=contract.model_dump(),
            compiler_confidence=contract.compiler_confidence,
            compiler_version=self._provider.version,
        )
        self._session.add(row)
        self._session.flush()
        return contract

    def _get_recent_contract(self, market_id: str) -> CompiledContract | None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_RECOMPILE_AFTER_HOURS)
        return (
            self._session.query(CompiledContract)
            .filter_by(raw_market_id=market_id)
            .order_by(CompiledContract.compiled_at.desc())
            .first()
        )
