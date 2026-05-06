import anyio
import random
import logging
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock
from parallax.execution.executor import ExecutionManager
from parallax.execution.mock_client import MockVenueClient
from parallax.shared.schemas import Leg

# [PHASE 4] Mock DB globally for stress test
import parallax.db.session
parallax.db.session.SessionLocal = MagicMock()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("StressTester")

async def run_stress_session(duration_s: int = 30):
    """
    Spawns massive concurrent execution attempts to stress test
    locking, fund management, and race conditions.
    """
    # 1. Setup Mock Clients
    kalshi_mock = MockVenueClient("kalshi", base_latency_ms=20, jitter_ms=10)
    poly_mock = MockVenueClient("polymarket", base_latency_ms=50, jitter_ms=30)
    
    # 2. Setup Execution Manager
    em = ExecutionManager()
    em.kalshi = kalshi_mock
    em.polymarket = poly_mock
    # Re-init balance service with mocks
    from parallax.execution.balance_service import BalanceService
    em.balance_service = BalanceService(kalshi_mock, poly_mock)
    
    logger.info(f"🚀 Starting Stress Session for {duration_s}s...")
    
    stats = {"success": 0, "fail": 0, "insufficient_funds": 0}
    
    async def worker(worker_id):
        while time.time() < end_time:
            # Generate a random basket
            basket = [
                {
                    "market_id": f"K_{random.randint(1,10)}", 
                    "platform": "kalshi", 
                    "price": 0.5, 
                    "quantity": random.randint(1, 100), 
                    "action": "BUY",
                    "outcome": "YES",
                    "side": "YES"
                },
                {
                    "market_id": f"P_{random.randint(1,10)}", 
                    "platform": "pm", 
                    "price": 0.45, 
                    "quantity": random.randint(1, 100), 
                    "action": "BUY",
                    "outcome": "YES",
                    "side": "YES"
                }
            ]
            
            try:
                # [PHASE 4] Concurrent execution attempt
                results = await em.execute_basket(basket)
                if not results:
                    stats["insufficient_funds"] += 1
                else:
                    # Filter out metadata like total_duration_ms
                    leg_results = [v for k, v in results.items() if isinstance(v, dict)]
                    if all(r and r.get("status") == "ok" for r in leg_results):
                        stats["success"] += 1
                    else:
                        stats["fail"] += 1
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                stats["fail"] += 1
                
            await anyio.sleep(random.uniform(0.01, 0.1))

    end_time = time.time() + duration_s
    
    async with anyio.create_task_group() as tg:
        for i in range(20): # 20 concurrent workers
            tg.start_soon(worker, i)
            
    logger.info("-" * 30)
    logger.info("Stress Test Results:")
    logger.info(f"Total Success: {stats['success']}")
    logger.info(f"Total Fail:    {stats['fail']}")
    logger.info(f"Total Insuff:  {stats['insufficient_funds']}")
    logger.info("-" * 30)

if __name__ == "__main__":
    anyio.run(run_stress_session)
