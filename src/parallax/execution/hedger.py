import asyncio
import logging
import uuid
from typing import List

from parallax.config import settings
from parallax.db.models import HedgeIntentRecord
from parallax.db.session import SessionLocal
from parallax.shared.schemas import Leg
from parallax.execution.kalshi_execution_client import KalshiExecutionClient
from parallax.execution.polymarket_execution_client import PolymarketExecutionClient
from parallax.ops.telemetry import broker

logger = logging.getLogger(__name__)

class UnwindEngine:
    """
    Handles emergency unwinding of positions when an arbitrage execution
    fails partially, leaving a directional risk.
    """

    def __init__(self):
        self.kalshi = KalshiExecutionClient()
        self.polymarket = PolymarketExecutionClient()

    async def handle_partial_fill(self, executed_legs: List[Leg], failed_legs: List[Leg], candidate_id: str):
        """
        Analyzes the execution mismatch and immediately unwinds the executed legs
        to return to a delta-neutral state (flat).
        """
        if not settings.runtime_auto_unwind_enabled:
            logger.warning("Unwind Engine is disabled. A manual intervention is required for Leg Mismatch!")
            asyncio.create_task(broker.broadcast("system_alert", {
                "level": "CRITICAL",
                "message": f"Partial fill on {candidate_id} but Auto-Unwind is disabled!"
            }))
            return

        if not executed_legs:
            logger.info("No legs executed, nothing to unwind.")
            return

        logger.warning(f"Unwind Engine triggered! {len(executed_legs)} succeeded, {len(failed_legs)} failed.")
        
        asyncio.create_task(broker.broadcast("system_alert", {
            "level": "WARNING",
            "message": f"LEG MISMATCH DETECTED. Unwinding {len(executed_legs)} legs."
        }))

        # [PERF] Offload blocking DB write (Bug #17)
        intent_id = uuid.uuid4()
        def persist_unwind_intent():
            try:
                with SessionLocal() as session:
                    # Convert candidate_id to UUID if it's a string from the runner
                    c_uuid = None
                    if candidate_id and isinstance(candidate_id, str) and "-" in candidate_id:
                        try:
                            c_uuid = uuid.UUID(candidate_id)
                        except ValueError:
                            pass
                    
                    intent = HedgeIntentRecord(
                        id=intent_id,
                        candidate_id=c_uuid,
                        legs_to_unwind=[leg.model_dump() for leg in executed_legs],
                        status="pending"
                    )
                    session.add(intent)
                    session.commit()
                    return True
            except Exception as e:
                logger.error(f"Failed to persist HedgeIntent: {e}")
                return False

        await asyncio.to_thread(persist_unwind_intent)

        unwind_tasks = []
        for leg in executed_legs:
            # Construct the opposite action
            opp_action = "SELL" if leg.action.upper() == "BUY" else "BUY"
            
            # Apply emergency slippage to guarantee execution
            max_slip = settings.runtime_max_unwind_slippage
            if opp_action == "SELL":
                # We are selling, accept a lower price
                unwind_price = leg.price * (1.0 - max_slip)
            else:
                # We are buying, accept a higher price
                unwind_price = leg.price * (1.0 + max_slip)
                
            # [REFINEMENT] Venue-specific rounding
            if leg.platform == "kalshi":
                unwind_price = round(unwind_price, 3)
            else:
                unwind_price = round(unwind_price, 2)

            unwind_leg = Leg(
                market_id=leg.market_id,
                outcome=leg.outcome,
                price=unwind_price,
                quantity=leg.quantity,
                action=opp_action,
                side=leg.side,
                token_id=leg.token_id,
                platform=leg.platform
            )

            logger.info(f"Unwinding {leg.platform} {leg.market_id}: {opp_action} {leg.side} @ {unwind_price}")
            
            if leg.platform == "kalshi":
                unwind_tasks.append(self.kalshi.execute_order(unwind_leg))
            elif leg.platform in ("polymarket", "pm"):
                unwind_tasks.append(self.polymarket.execute_order(unwind_leg))
        
        # Execute the dumps concurrently
        unwind_results = await asyncio.gather(*unwind_tasks, return_exceptions=True)
        
        # Log the aftermath and update intent status
        successes = 0
        fatal_errors = []
        for m_id, res in zip([leg.market_id for leg in executed_legs], unwind_results):
            if isinstance(res, Exception) or res is None:
                err_msg = f"FATAL: Unwind failed for {m_id}. Error: {res}"
                logger.error(err_msg)
                fatal_errors.append(err_msg)
            else:
                successes += 1
                logger.info(f"Unwind successful for {m_id}")

        # [PERF] Non-blocking intent update
        def finalize_intent():
            try:
                with SessionLocal() as session:
                    intent = session.query(HedgeIntentRecord).filter_by(id=intent_id).first()
                    if intent:
                        if successes == len(executed_legs):
                            intent.status = "completed"
                        else:
                            intent.status = "failed"
                            intent.error_message = "\n".join(fatal_errors)
                        session.commit()
            except Exception as e:
                logger.error(f"Failed to update HedgeIntent {intent_id}: {e}")

        await asyncio.to_thread(finalize_intent)

        asyncio.create_task(broker.broadcast("unwind_executed", {
            "candidate_id": str(candidate_id),
            "successes": successes,
            "total_unwound": len(executed_legs)
        }))
