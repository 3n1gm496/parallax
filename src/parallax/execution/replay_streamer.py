import asyncio
import logging
import aiofiles
from typing import Callable, Awaitable
from datetime import datetime

from parallax.config import settings
from parallax.execution.schemas import OrderbookSnapshot

logger = logging.getLogger(__name__)

class ReplayStreamer:
    """
    Simulates the live OrderbookStreamer by playing back a recorded JSONL file
    of OrderbookSnapshots.
    """
    
    def __init__(self):
        self.orderbooks: dict[str, OrderbookSnapshot] = {}
        self.callbacks: list[Callable[[str], Awaitable[None]]] = []
        self._running = False
        self._replay_task: asyncio.Task | None = None
        self.replay_file = settings.runtime_replay_file
        self.speed_factor = settings.runtime_replay_speed_factor

    def subscribe(self, callback: Callable[[str], Awaitable[None]]):
        self.callbacks.append(callback)

    async def _emit(self, market_id: str):
        for cb in self.callbacks:
            try:
                await cb(market_id)
            except Exception as e:
                logger.error(f"Error in replay streamer callback for {market_id}: {e}")

    async def start(self, market_registry: dict[str, dict]):
        """
        Starts reading the JSONL file and emitting snapshots.
        """
        if not self.replay_file:
            logger.error("No runtime_replay_file specified in config.")
            return

        self._running = True
        logger.info(f"Starting ReplayStreamer reading from {self.replay_file}")
        self._replay_task = asyncio.create_task(self._playback_loop())

    async def stop(self):
        self._running = False
        if self._replay_task:
            self._replay_task.cancel()
            try:
                await self._replay_task
            except asyncio.CancelledError:
                pass
        logger.info("Stopped ReplayStreamer.")

    async def _playback_loop(self):
        try:
            last_timestamp: datetime | None = None

            async with aiofiles.open(self.replay_file, mode='r') as f:
                async for line in f:
                    if not self._running:
                        break
                    
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        snapshot = OrderbookSnapshot.model_validate_json(line)
                    except Exception as e:
                        logger.warning(f"Skipping invalid snapshot line: {e}")
                        continue

                    if self.speed_factor > 0 and last_timestamp is not None:
                        # Calculate time delta
                        delta = (snapshot.captured_at - last_timestamp).total_seconds()
                        if delta > 0:
                            sleep_time = delta * self.speed_factor
                            # Cap sleep time to avoid extremely long pauses if the recording had a gap
                            if sleep_time > 10.0:
                                sleep_time = 10.0
                            await asyncio.sleep(sleep_time)

                    last_timestamp = snapshot.captured_at
                    
                    self.orderbooks[snapshot.market_id] = snapshot
                    await self._emit(snapshot.market_id)
                    
            logger.info("Replay playback completed.")
        except FileNotFoundError:
            logger.error(f"Replay file {self.replay_file} not found.")
        except Exception as e:
            logger.error(f"Error during playback loop: {e}")
            
        self._running = False
