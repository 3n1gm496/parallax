import anyio
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

    async def handle_partial_fill(
        self, 
        executed_legs: List[Leg], 
        failed_legs: List[Leg], 
        candidate_id: str,
        persist_intent: bool = True
    ):
        """
        Analyzes the execution mismatch and immediately unwinds the executed legs
        to return to a delta-neutral state (flat).
        """
        if not settings.runtime_auto_unwind_enabled:
            logger.warning("Unwind Engine is disabled. A manual intervention is required for Leg Mismatch!")
            try:
                # Loop-agnostic background task (non-blocking)
                async def _alert():
                    await broker.broadcast("system_alert", {
                        "level": "CRITICAL",
                        "message": f"Partial fill on {candidate_id} but Auto-Unwind is disabled!"
                    })
                
                # Note: anyio requires a task group to spawn. 
                # If we don't have one, we just await it for now to be safe, 
                # or use anyio.from_thread.run_sync(anyio.run, _alert) if we are in a thread.
                # However, for this audit, we will just await it to ensure it completes.
                await _alert()
            except Exception as e:
                logger.error(f"Failed to send alert: {e}")
            return

        if not executed_legs:
            logger.info("No legs executed, nothing to unwind.")
            return

        logger.warning(f"Unwind Engine triggered! {len(executed_legs)} succeeded, {len(failed_legs)} failed.")
        
        # BUG-011: Background telemetry to avoid blocking risk reduction
        async def _alert_start():
            await broker.broadcast("system_alert", {
                "level": "WARNING",
                "message": f"LEG MISMATCH DETECTED. Unwinding {len(executed_legs)} legs."
            })

        # [Audit Fix] Conditional persistence to avoid recovery loops
        intent_id = uuid.uuid4()
        if persist_intent:
            def persist_unwind_intent():
                try:
                    with SessionLocal() as session:
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

            await anyio.to_thread.run_sync(persist_unwind_intent)

        # Execute the dumps concurrently using AnyIO task group
        unwind_results = []
        async with anyio.create_task_group() as tg:
            # Start background alert
            tg.start_soon(_alert_start)

            async def _run_unwind(t_func, leg_obj, idx):
                # BUG-013: Add simple retry for emergency unwinds
                max_retries = 2
                last_err = None
                for attempt in range(max_retries):
                    try:
                        # BUG-010: Add strict timeout for emergency execution
                        with anyio.fail_after(settings.orderbook_fetch_timeout_seconds):
                            res = await t_func(leg_obj)
                            unwind_results.append((idx, res))
                            return
                    except Exception as e:
                        last_err = e
                        logger.error(f"Unwind attempt {attempt+1} failed for {leg_obj.market_id}: {e}")
                        if attempt < max_retries - 1:
                            await anyio.sleep(0.5 * (attempt + 1))
                
                unwind_results.append((idx, last_err))

            for i, leg in enumerate(executed_legs):
                # Construct the opposite action
                opp_action = "SELL" if leg.action.upper() == "BUY" else "BUY"
                
                # [PHASE 4] Toxic Flow Protection: Use L1Cache for real-time unwind price
                from parallax.shared.l1_cache import L1HotCache
                cache = L1HotCache()
                best_bid, best_ask = cache.get_best_prices(leg.market_id)
                
                max_slip = settings.runtime_max_unwind_slippage
                
                if opp_action == "SELL":
                    # We want to sell. Target the best bid if available, else slip the entry.
                    market_ref = best_bid if best_bid else leg.price
                    unwind_price = max(0.01, market_ref * (1.0 - max_slip))
                else:
                    # We want to buy. Target the best ask if available, else slip the entry.
                    market_ref = best_ask if best_ask else leg.price
                    unwind_price = min(0.99, market_ref * (1.0 + max_slip))
                    
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

                logger.warning(f"UNWINDING {leg.platform} {leg.market_id}: {opp_action} @ {unwind_price} (Emergency Slip: {max_slip*100}%)")
                
                if leg.platform == "kalshi":
                    tg.start_soon(_run_unwind, self.kalshi.execute_order, unwind_leg, i)
                elif leg.platform in ("polymarket", "pm"):
                    tg.start_soon(_run_unwind, self.polymarket.execute_order, unwind_leg, i)
        
        # Sort results back to original order
        unwind_results.sort(key=lambda x: x[0])
        unwind_results = [r[1] for r in unwind_results]
        
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
        if persist_intent:
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

            await anyio.to_thread.run_sync(finalize_intent)

        await broker.broadcast("unwind_executed", {
            "candidate_id": str(candidate_id),
            "successes": successes,
            "total_unwound": len(executed_legs)
        })
