import anyio
import logging
from typing import Set, Dict, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class TelemetryBroker:
    """
    A backend-agnostic pub/sub broker using AnyIO memory object streams.
    """
    def __init__(self):
        # Stores the send-half of the memory stream
        self._senders: Set[anyio.abc.ObjectSendStream] = set()

    def subscribe(self, buffer_size: int = 100) -> Tuple[anyio.abc.ObjectSendStream, anyio.abc.ObjectReceiveStream]:
        # BUG-040: Add explicit buffer limit to prevent unbounded memory growth
        send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=buffer_size)
        self._senders.add(send_stream)
        return send_stream, receive_stream

    def unsubscribe(self, send_stream: anyio.abc.ObjectSendStream):
        # BUG-039: Ensure send stream is closed and removed to prevent memory leaks
        if send_stream in self._senders:
            self._senders.remove(send_stream)
            try:
                send_stream.close()
            except Exception:
                pass

    async def broadcast(self, topic: str, payload: Dict[str, Any]):
        """
        Sends an event to all connected clients concurrently.
        """
        message = {
            "topic": topic,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload
        }
        
        # BUG-041: Concurrent broadcast to avoid blocking the sender
        # Use a list of dead senders to clean up after the loop
        dead_senders = []
        
        for sender in list(self._senders):
            try:
                # BUG-044: Use non-blocking try_send or clone to avoid hanging
                sender.send_nowait(message)
            except (anyio.WouldBlock, anyio.ClosedResourceError):
                # If the buffer is full (slow consumer) or closed, we mark for cleanup
                # In a real HFT app, we might want to evict the oldest instead of dropping the newest
                if isinstance(sender, anyio.ClosedResourceError):
                    dead_senders.append(sender)
                else:
                    logger.warning(f"Telemetry buffer full for a consumer, dropping message on {topic}")
            except Exception as e:
                logger.error(f"Unexpected error in telemetry broadcast: {e}")
                dead_senders.append(sender)

        for dead in dead_senders:
            self.unsubscribe(dead)

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
