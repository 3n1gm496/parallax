from __future__ import annotations
from abc import ABC, abstractmethod
from parallax.shared.schemas import ContractSchema, RawMarketData


class CompilerProvider(ABC):
    """Compile a raw market's natural-language spec into a structured ContractSchema."""

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    async def compile(self, market: RawMarketData) -> ContractSchema: ...
