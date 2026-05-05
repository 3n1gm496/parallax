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


class FallbackProvider(CompilerProvider):
    """
    Tries a list of providers in order. Useful for Anthropic -> Local fallback.
    """
    def __init__(self, providers: list[CompilerProvider]):
        self.providers = providers

    @property
    def version(self) -> str:
        return f"fallback({','.join(p.version for p in self.providers)})"

    async def compile(self, market: RawMarketData) -> ContractSchema:
        last_err = None
        for provider in self.providers:
            try:
                return await provider.compile(market)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Provider {provider.version} failed: {e}. Trying next...")
                last_err = e
        raise last_err
