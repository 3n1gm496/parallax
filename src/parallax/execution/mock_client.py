import anyio
import random
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class MockVenueClient:
    """
    [PHASE 4] A configurable mock client for stress testing.
    Simulates network latency, partial fills, and occasional API errors.
    """
    def __init__(self, platform: str, base_latency_ms: float = 10.0, jitter_ms: float = 5.0):
        self.platform = platform
        self.base_latency = base_latency_ms / 1000.0
        self.jitter = jitter_ms / 1000.0
        self.balances: Dict[str, float] = {"USD": 10000.0, "USDC": 10000.0}

    async def get_balance(self) -> float:
        await anyio.sleep(self.base_latency + random.uniform(0, self.jitter))
        return self.balances.get("USD", 0.0) if self.platform == "kalshi" else self.balances.get("USDC", 0.0)

    async def execute_order(self, leg: Any) -> Dict[str, Any]:
        # Simulate network latency
        latency = self.base_latency + random.uniform(0, self.jitter)
        await anyio.sleep(latency)
        
        # 2% chance of API failure
        if random.random() < 0.02:
            raise Exception(f"Simulated API Error on {self.platform}")
            
        # 5% chance of partial fill (return 'pending' or similar)
        if random.random() < 0.05:
            return {"status": "partial", "filled": leg.quantity * 0.5, "order_id": "mock_part"}
            
        # Success
        cost = leg.price * leg.quantity
        if self.platform == "kalshi":
            self.balances["USD"] -= cost
        else:
            self.balances["USDC"] -= cost
            
        return {"status": "ok", "order_id": "mock_ok", "cost": cost}
