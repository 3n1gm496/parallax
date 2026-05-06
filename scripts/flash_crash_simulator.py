import anyio
import logging
from unittest.mock import MagicMock
from parallax.execution.executor import ExecutionManager
from parallax.execution.mock_client import MockVenueClient
from parallax.shared.l1_cache import L1HotCache
from parallax.execution.schemas import OrderbookSnapshot, OrderbookSide, OrderbookLevel
from datetime import datetime, timezone

# Mock DB
import parallax.db.session
parallax.db.session.SessionLocal = MagicMock()

import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FlashCrash")

def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}")
    sys.stdout.flush()

async def run_crash_simulation():
    log("🌊 Initializing Flash Crash Simulation...")
    
    # 1. Setup Clients
    kalshi = MockVenueClient("kalshi", base_latency_ms=100) # High latency to allow crash mid-flight
    poly = MockVenueClient("polymarket", base_latency_ms=100)
    
    em = ExecutionManager()
    em.kalshi = kalshi
    em.polymarket = poly
    
    cache = L1HotCache()
    
    # 2. Setup initial market state in L1 Cache
    m_id = "CRASH_1"
    # Buy @ 0.50
    snapshot = OrderbookSnapshot(
        id="s1", platform="kalshi", market_id=m_id, outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=0.49, size=100)]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=0.50, size=100)])
    )
    cache.update_from_snapshot(snapshot)
    
    basket = [
        {"market_id": m_id, "platform": "kalshi", "price": 0.50, "quantity": 100, "action": "BUY", "outcome": "YES", "side": "YES"},
        {"market_id": "LEG_2", "platform": "polymarket", "price": 0.45, "quantity": 100, "action": "BUY", "outcome": "YES", "side": "YES"}
    ]
    
    # 3. Simulate failure on Leg 2 to trigger Unwind
    em.polymarket.execute_order = MagicMock(side_effect=Exception("Polymarket CRASHED"))
    
    logger.info("🔥 Triggering execution with simulated Leg 2 failure...")
    
    # Start execution in background
    async def run_exec():
        try:
            await em.execute_basket(basket)
        except Exception as e:
            logger.error(f"Execution failed as expected: {e}")

    # Move market by 20% in L1 Cache while execution is "pending" (latencies are 100ms)
    async def trigger_crash():
        await anyio.sleep(0.05) # Halfway through latency
        log("📉 FLASH CRASH! Market price dropping from 0.50 to 0.30...")
        crash_snap = OrderbookSnapshot(
            id="s2", platform="kalshi", market_id=m_id, outcome="YES",
            captured_at=datetime.now(timezone.utc),
            bids=OrderbookSide(levels=[OrderbookLevel(price=0.29, size=100)]),
            asks=OrderbookSide(levels=[OrderbookLevel(price=0.30, size=100)])
        )
        cache.update_from_snapshot(crash_snap)
        log(f"New Cache Price for {m_id}: {cache.get_best_prices(m_id)}")

    log("🚀 Starting simulation task group...")
    async with anyio.create_task_group() as tg:
        tg.start_soon(run_exec)
        tg.start_soon(trigger_crash)
    
    log("✅ Flash Crash simulation finished.")

if __name__ == "__main__":
    anyio.run(run_crash_simulation)
