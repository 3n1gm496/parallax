from __future__ import annotations
from abc import ABC, abstractmethod
from parallax.shared.schemas import RawMarketData


class PlatformAdapter(ABC):
    """Fetch raw market data from one prediction-market platform."""

    @property
    @abstractmethod
    def platform_name(self) -> str: ...

    @abstractmethod
    async def fetch_markets(self) -> list[RawMarketData]: ...
