import asyncio
import logging
from typing import Set, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class TelemetryBroker:
    """
    A simple in-memory pub/sub broker to push events to WebSocket clients.
    """
    def __init__(self):
        self._queues: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, topic: str, payload: Dict[str, Any]):
        """
        Sends an event to all connected websocket clients.
        """
        message = {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload
        }
        for q in list(self._queues):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Telemetry queue full, dropping message.")

def setup_async_logging():
    """
    Wraps existing log handlers in a QueueHandler to make logging non-blocking (Bug #19).
    """
    import logging.handlers
    import queue

    log_queue = queue.Queue(-1)  # Unlimited size
    queue_handler = logging.handlers.QueueHandler(log_queue)
    
    root = logging.getLogger()
    # Move existing handlers to QueueListener
    handlers = root.handlers[:]
    for h in handlers:
        root.removeHandler(h)
    
    root.addHandler(queue_handler)
    
    listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)
    listener.start()
    return listener

# Global singleton
broker = TelemetryBroker()
