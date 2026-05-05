import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from parallax.ops.telemetry import broker
from parallax.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])

@router.websocket("/stream")
async def telemetry_stream(websocket: WebSocket):
    await websocket.accept()
    queue = broker.subscribe()
    logger.info("New telemetry client connected.")
    
    try:
        while True:
            # We wait for either a client disconnect or a message from the queue
            if websocket.client_state == WebSocketState.DISCONNECTED:
                break
                
            message = await queue.get()
            await websocket.send_json(message)
            queue.task_done()
    except WebSocketDisconnect:
        logger.info("Telemetry client disconnected.")
    except Exception as e:
        logger.error(f"Error in websocket stream: {e}")
    finally:
        broker.unsubscribe(queue)


@router.post("/kill-switch/hard")
async def hard_kill_switch():
    """
    Immediately halt the python runtime (simulated or real process exit).
    """
    logger.critical("HARD KILL SWITCH INITIATED via War Room")
    await broker.broadcast("system_alert", {"level": "CRITICAL", "message": "HARD KILL INITIATED"})
    
    # In a real system we would use os._exit(1) or send a signal.
    # For now we'll set a global state or schedule an exit
    import os
    import signal
    
    def kill_process():
        os.kill(os.getpid(), signal.SIGTERM)
        
    # Give the UI 1 second to receive the broadcast before dying
    asyncio.get_event_loop().call_later(1.0, kill_process)
    return {"status": "shutting_down", "type": "hard"}


@router.post("/kill-switch/soft")
async def soft_kill_switch():
    """
    Gracefully unwind positions and halt further trading.
    """
    logger.warning("SOFT KILL SWITCH INITIATED via War Room")
    await broker.broadcast("system_alert", {"level": "WARNING", "message": "SOFT KILL (UNWIND) INITIATED"})
    
    # Here we would invoke the Unwind Engine to close out open positions
    # and flip a runtime flag to stop new candidates from executing.
    settings.runtime_live_execution_enabled = False
    
    await broker.broadcast("status_update", {"execution_enabled": False, "unwinding": True})
    return {"status": "unwinding", "type": "soft"}
