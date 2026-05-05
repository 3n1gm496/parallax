import asyncio
import logging

from parallax.db.models import HedgeIntentRecord
from parallax.db.session import SessionLocal
from parallax.shared.schemas import Leg
from parallax.execution.hedger import UnwindEngine

logger = logging.getLogger(__name__)

async def run_hedge_recovery():
    """
    Scans the database for 'pending' or 'failed' hedge intents and attempts
    to re-execute them. This is critical for recovering from crashes mid-unwind.
    """
    logger.info("Starting Hedge Recovery Task...")
    
    with SessionLocal() as session:
        pending_intents = session.query(HedgeIntentRecord).filter(
            HedgeIntentRecord.status.in_(["pending", "failed"]),
            HedgeIntentRecord.retry_count < 3
        ).all()
        
        if not pending_intents:
            logger.info("No pending hedge intents found.")
            return

        logger.warning(f"Found {len(pending_intents)} pending/failed hedge intents. Attempting recovery...")
        
        engine = UnwindEngine()
        
        for intent in pending_intents:
            logger.info(f"Recovering HedgeIntent {intent.id} (Candidate: {intent.candidate_id})...")
            
            # Reconstruct legs from JSON
            try:
                legs = [Leg(**leg_data) for leg_data in intent.legs_to_unwind]
            except Exception as e:
                logger.error(f"Failed to reconstruct legs for intent {intent.id}: {e}")
                intent.status = "error"
                intent.error_message = f"Reconstruction failed: {e}"
                session.commit()
                continue

            # Increment retry count
            intent.retry_count += 1
            session.commit()

            # Execute unwind (this is already idempotent/safe to retry)
            # We call handle_partial_fill directly, but it creates its OWN record currently.
            # Actually, handle_partial_fill in hedger.py now creates a NEW intent.
            # This is slightly redundant but safe. 
            # Ideally, we should refactor hedger.py to separate "record-keeping" from "execution".
            
            # For now, let's just trigger the engine. 
            # Note: handle_partial_fill is async.
            try:
                await engine.handle_partial_fill(
                    executed_legs=legs, 
                    failed_legs=[], # We only care about unwinding the executed ones
                    candidate_id=str(intent.candidate_id or "recovered")
                )
                
                # Mark the ORIGINAL intent as 'superseded' or 'completed'
                intent.status = "completed"
                session.commit()
            except Exception as e:
                logger.error(f"Recovery failed for intent {intent.id}: {e}")
                intent.error_message = f"Recovery attempt failed: {e}"
                session.commit()

    logger.info("Hedge Recovery Task complete.")

if __name__ == "__main__":
    # Quick manual test
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_hedge_recovery())
