import asyncio
import logging
import time
import uuid

from parallax.config import settings
from parallax.shared.schemas import Leg
from parallax.execution.kalshi_execution_client import KalshiExecutionClient
from parallax.execution.polymarket_execution_client import PolymarketExecutionClient

logger = logging.getLogger(__name__)

class ExecutionManager:
    """Coordinates execution across different venues."""
    
    # [Opp 15] Circuit Breaker state
    _circuit_breakers: dict[str, float] = {
        "kalshi": 0.0,
        "polymarket": 0.0,
        "pm": 0.0,
    }
    
    CIRCUIT_BREAKER_TIMEOUT_S = 60.0 # Trip for 60 seconds on failure

    def __init__(self):
        self.kalshi = KalshiExecutionClient()
        self.polymarket = PolymarketExecutionClient()

    @classmethod
    def trip_circuit_breaker(cls, platform: str):
        logger.error(f"🔌 CIRCUIT BREAKER TRIPPED for venue: {platform}")
        cls._circuit_breakers[platform] = time.time() + cls.CIRCUIT_BREAKER_TIMEOUT_S

    @classmethod
    def is_venue_healthy(cls, platform: str) -> bool:
        return time.time() > cls._circuit_breakers.get(platform, 0.0)

    async def execute_basket(self, selected_legs: list[dict]) -> dict:
        """
        Executes an optimal basket of legs concurrently.
        `selected_legs` is the list of dictionaries from BasketOptimizer.
        Returns a dict of responses mapped by market_id.
        """
        if not settings.runtime_live_execution_enabled and not settings.runtime_dry_run:
            logger.info("Live execution and dry run are both disabled. Skipping execution.")
            return {}

        # [Opp 15] Check circuit breakers for all required venues before executing
        required_venues = {leg.get("platform", "polymarket") for leg in selected_legs}
        for venue in required_venues:
            if not self.is_venue_healthy(venue):
                logger.warning(f"Execution rejected: Venue {venue} is currently under circuit breaker.")
                return {}

        logger.info(f"ExecutionManager: processing {len(selected_legs)} legs.")
        
        tasks = []
        market_ids = []
        leg_objects = []
        
        for leg_dict in selected_legs:
            # Reconstruct Leg model loosely
            leg = Leg(
                market_id=leg_dict["market_id"],
                outcome=leg_dict["outcome"],
                price=leg_dict["price"],
                quantity=leg_dict["quantity"],  # The quantity to buy from optimizer
                cost=leg_dict.get("cost"),
                side=leg_dict["side"],
                token_id=leg_dict.get("token_id"),
                platform=leg_dict.get("platform", "polymarket"), # Default polymarket if missing
                action=leg_dict.get("action", "BUY") # [BUG FIX] Ensure action (BUY/SELL) is propagated
            )
            
            market_ids.append(leg.market_id)
            leg_objects.append(leg)
            
            # [Opp 14] Self-Healing Hedging: Add execution timeout
            timeout_s = settings.runtime_max_execution_wait_seconds if hasattr(settings, "runtime_max_execution_wait_seconds") else 2.0

            if leg.platform == "kalshi":
                tasks.append(asyncio.wait_for(self.kalshi.execute_order(leg), timeout=timeout_s))
            elif leg.platform in ("polymarket", "pm"):
                tasks.append(asyncio.wait_for(self.polymarket.execute_order(leg), timeout=timeout_s))
            else:
                logger.warning(f"Unknown platform for leg {leg.market_id}: {leg.platform}")
                # Append a dummy task so the lengths match
                async def mock_fail(): return None
                tasks.append(mock_fail())


        # [PERF] Offload blocking DB write to a thread (Bug #17)
        def persist_intent():
            from parallax.db.session import SessionLocal
            from parallax.db.models import HedgeIntentRecord
            with SessionLocal() as session:
                intent = HedgeIntentRecord(
                    candidate_id=uuid.UUID(selected_legs[0]["candidate_id"]) if "candidate_id" in selected_legs[0] else None,
                    legs_to_unwind={"legs": selected_legs},
                    status="pending"
                )
                session.add(intent)
                session.commit()
                return intent.id

        intent_id = await asyncio.to_thread(persist_intent)

        # Execute concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # [PERF] Non-blocking status update
        def update_intent_status():
            from parallax.db.session import SessionLocal
            from parallax.db.models import HedgeIntentRecord
            with SessionLocal() as session:
                intent = session.get(HedgeIntentRecord, intent_id)
                if intent:
                    intent.status = "completed"
                    session.commit()

        await asyncio.to_thread(update_intent_status)
        
        execution_report = {}
        executed_legs = []
        failed_legs = []
        
        for leg, res in zip(leg_objects, results):
            m_id = leg.market_id
            if isinstance(res, Exception) or res is None:
                logger.error(f"Execution error for {m_id}: {res}")
                execution_report[m_id] = None
                failed_legs.append(leg)
            else:
                execution_report[m_id] = res
                executed_legs.append(leg)
                
        # Trigger Unwind if partial fill
        if executed_legs and failed_legs:
            # We must use the unwind engine
            from parallax.execution.hedger import UnwindEngine
            hedger = UnwindEngine()
            # We don't have candidate_id here cleanly, we can pass "unknown" or pass it in
            asyncio.create_task(hedger.handle_partial_fill(executed_legs, failed_legs, "basket_unwind"))

        return execution_report
