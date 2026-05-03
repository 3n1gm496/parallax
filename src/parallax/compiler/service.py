from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from parallax.compiler.contract_compiler import ContractCompiler
from parallax.compiler.provider import CompilerProvider
from parallax.db.models import CompiledContract, CompiledProposition
from parallax.shared.schemas import CompiledPropositionSchema, ContractSchema

_RECOMPILE_AFTER_HOURS = 24


class CompilerService:
    """Compile a RawMarket into a ContractSchema and persist as CompiledContract."""

    def __init__(self, session: Session, provider: CompilerProvider) -> None:
        self._session = session
        self._provider = provider
        self._contract_compiler = ContractCompiler(provider)

    async def compile(self, market) -> ContractSchema:
        existing = self._get_recent_contract(market.id)
        if existing is not None and self._should_reuse_contract(existing, market):
            return ContractSchema.model_validate(existing.contract_json)

        contract, proposition = await self._contract_compiler.compile_market(market)

        row = CompiledContract(
            id=uuid.uuid4(),
            raw_market_id=market.id,
            contract_json=contract.model_dump(),
            compiler_confidence=contract.compiler_confidence,
            compiler_version=self._contract_compiler.version,
        )
        self._session.add(row)
        self._upsert_compiled_proposition(proposition)
        self._session.flush()
        return contract

    def _get_recent_contract(self, market_id: str) -> CompiledContract | None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_RECOMPILE_AFTER_HOURS)
        return (
            self._session.query(CompiledContract)
            .filter(
                CompiledContract.raw_market_id == market_id,
                CompiledContract.compiled_at >= cutoff,
            )
            .order_by(CompiledContract.compiled_at.desc())
            .first()
        )

    def _should_reuse_contract(self, existing: CompiledContract, market) -> bool:
        if existing.compiler_version != self._provider.version:
            return False

        market_updated_at = getattr(market, "updated_at", None)
        if market_updated_at is not None and existing.compiled_at < market_updated_at:
            return False
        return True

    def get_compiled_proposition(self, market_id: str) -> CompiledPropositionSchema | None:
        row = (
            self._session.query(CompiledProposition)
            .filter(CompiledProposition.raw_market_id == market_id)
            .order_by(CompiledProposition.compiled_at.desc())
            .first()
        )
        return CompiledPropositionSchema.model_validate(row.proposition_json) if row else None

    def _upsert_compiled_proposition(self, proposition: CompiledPropositionSchema) -> None:
        row = (
            self._session.query(CompiledProposition)
            .filter(CompiledProposition.raw_market_id == proposition.raw_market_id)
            .first()
        )
        payload = proposition.model_dump()
        if row is None:
            row = CompiledProposition(
                id=uuid.uuid4(),
                raw_market_id=proposition.raw_market_id,
                proposition_json=payload,
            compiler_version=self._contract_compiler.version,
            )
            self._session.add(row)
        else:
            row.proposition_json = payload
            row.compiler_version = self._contract_compiler.version
