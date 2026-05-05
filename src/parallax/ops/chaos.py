import asyncio
import random
import logging

from parallax.config import settings

logger = logging.getLogger(__name__)

class ChaosMonkey:
    """
    [Opp 12] Chaos Engineering Suite
    Injects artificial latency and network drops to test engine resilience.
    Enabled via PARALLAX_CHAOS_MODE=1 in environment.
    """
    
    def __init__(self):
        self.enabled = getattr(settings, "chaos_mode_enabled", False)
        self.drop_probability = getattr(settings, "chaos_drop_probability", 0.05)
        self.latency_ms_min = getattr(settings, "chaos_latency_ms_min", 10)
        self.latency_ms_max = getattr(settings, "chaos_latency_ms_max", 500)
        
        if self.enabled:
            logger.warning("🐒 CHAOS MONKEY IS ACTIVE! Expect artificial delays and dropped packets.")

    async def intercept_network_call(self, venue: str) -> bool:
        """
        Applies chaos to a network call.
        Returns True if the packet should be DROPpED (simulated failure).
        Returns False if it should proceed (potentially after artificial delay).
        """
        if not self.enabled:
            return False
            
        # 1. Packet Drop
        if random.random() < self.drop_probability:
            logger.error(f"🐒 CHAOS: Dropping packet for {venue}")
            return True
            
        # 2. Artificial Latency
        delay_ms = random.uniform(self.latency_ms_min, self.latency_ms_max)
        if delay_ms > 100:
            logger.warning(f"🐒 CHAOS: Injecting {delay_ms:.0f}ms latency for {venue}")
        await asyncio.sleep(delay_ms / 1000.0)
        
        return False

# Global singleton
chaos_monkey = ChaosMonkey()
