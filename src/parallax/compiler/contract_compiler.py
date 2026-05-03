from __future__ import annotations

from parallax.compiler.proposition_normalizer import build_compiled_proposition, enrich_contract
from parallax.compiler.provider import CompilerProvider
from parallax.shared.schemas import CompiledPropositionSchema, ContractSchema, RawMarketData


class ContractCompiler:
    """Compile raw market text into contract and proposition-level semantics."""

    def __init__(self, provider: CompilerProvider) -> None:
        self._provider = provider

    @property
    def version(self) -> str:
        return self._provider.version

    async def compile_market(self, market) -> tuple[ContractSchema, CompiledPropositionSchema]:
        _mid = market.market_id
        market_id_str = _mid if isinstance(_mid, str) else market.id.split(":")[-1]
        resolution_source = getattr(market, "resolution_source", None)
        if not isinstance(resolution_source, str):
            resolution_source = None
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
            resolution_source=resolution_source,
            raw_payload=dict(market.raw_payload) if market.raw_payload else {},
        )
        contract = await self._provider.compile(market_data)
        proposition = build_compiled_proposition(market, contract, raw_market_id=market.id)
        return enrich_contract(contract, proposition), proposition
