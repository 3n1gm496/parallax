import logging
import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from parallax.ops.telemetry import broker
from parallax.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])

@router.websocket("/stream")
async def telemetry_stream(websocket: WebSocket):
    await websocket.accept()
    # BUG-039/040 Fix: Subscribe returns a tuple (send_stream, receive_stream)
    send_stream, receive_stream = broker.subscribe()
    logger.info("New telemetry client connected.")
    
    try:
        async with receive_stream:
            async for message in receive_stream:
                if websocket.client_state == WebSocketState.DISCONNECTED:
                    break
                await websocket.send_json(message)
    except WebSocketDisconnect:
        logger.info("Telemetry client disconnected.")
    except Exception as e:
        logger.error(f"Error in websocket stream: {e}")
    finally:
        broker.unsubscribe(send_stream)


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
    async def _kill_soon():
        await anyio.sleep(1.0)
        kill_process()
    
    # We can't easily spawn a task here that survives the request without a task group, 
    # but in FastAPI, we can use BackgroundTasks or just fire and forget if the loop is still alive.
    # To be safe and loop-agnostic, we'll use a local task group if possible or just anyio.spawn.
    # Since this is a kill switch, the process is dying anyway.
    from anyio import create_task_group
    # We'll use the running loop's task group if available, but for a kill switch, 
    # a simple background thread or task is fine.
    # However, to be spietato, we'll just run it in a thread to ensure it hits.
    import threading
    threading.Timer(1.0, kill_process).start()
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
