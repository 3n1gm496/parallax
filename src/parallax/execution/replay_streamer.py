import anyio
import logging
import time
from typing import Callable, Awaitable
from datetime import datetime

import msgspec
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
        self._tg_cm = None
        self._tg = None
        self.replay_file = settings.runtime_replay_file
        self.speed_factor = settings.runtime_replay_speed_factor
        self._prefetched_snapshots: list[OrderbookSnapshot] = []
        self._decoder = msgspec.json.Decoder(OrderbookSnapshot)

    def subscribe(self, callback: Callable[[str], Awaitable[None]]):
        self.callbacks.append(callback)

    async def prefetch_all(self):
        """
        [PHASE 3] Drastically optimized pre-fetch using synchronous I/O and msgspec.
        """
        if not self.replay_file:
            return
            
        logger.info(f"Prefetching snapshots from {self.replay_file} (Sync I/O)...")
        start_t = time.perf_counter()
        
        try:
            # Synchronous read is much faster for local SSD/NVMe files during init
            with open(self.replay_file, 'rb') as f:
                lines = f.readlines()
            
            # Use list comprehension for tight C-loop speed
            self._prefetched_snapshots = [self._decoder.decode(line) for line in lines if line.strip()]
            
            count = len(self._prefetched_snapshots)
            elapsed = time.perf_counter() - start_t
            logger.info(f"Prefetched {count} snapshots in {elapsed:.4f}s ({count/elapsed:.0f} ticks/s)")
        except Exception as e:
            logger.error(f"Prefetch failed: {e}")

    async def _emit(self, market_id: str):
        # [PHASE 3] Optimized emission: avoid task group for small number of callbacks
        if not self.callbacks:
            return
            
        if len(self.callbacks) == 1:
            await self.callbacks[0](market_id)
            return

        async with anyio.create_task_group() as tg:
            for cb in self.callbacks:
                tg.start_soon(cb, market_id)

    async def start(self, market_registry: dict[str, dict]):
        """
        Starts reading the JSONL file and emitting snapshots.
        """
        if not self.replay_file:
            logger.error("No runtime_replay_file specified in config.")
            return

        if not self._prefetched_snapshots:
            await self.prefetch_all()

        self._running = True
        logger.info("Starting ReplayStreamer loop.")
        
        # Loop-agnostic background task management
        self._tg_cm = anyio.create_task_group()
        self._tg = await self._tg_cm.__aenter__()
        self._tg.start_soon(self._playback_loop)

    async def stop(self):
        self._running = False
        if self._tg_cm:
            try:
                # This will cancel all tasks in the group if we use tg.cancel_scope.cancel()
                # or we just wait for them to finish/cancel.
                await self._tg_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error closing ReplayStreamer task group: {e}")
            finally:
                self._tg_cm = None
                self._tg = None
        logger.info("Stopped ReplayStreamer.")

    async def _playback_loop(self):
        try:
            last_timestamp: datetime | None = None
            
            for snapshot in self._prefetched_snapshots:
                if not self._running:
                    break

                if self.speed_factor > 0 and last_timestamp is not None:
                    delta = (snapshot.captured_at - last_timestamp).total_seconds()
                    if delta > 0:
                        sleep_time = delta * self.speed_factor
                        if sleep_time > 10.0:
                            sleep_time = 10.0
                        await anyio.sleep(sleep_time)

                last_timestamp = snapshot.captured_at
                self.orderbooks[snapshot.market_id] = snapshot
                
                # Hot emission
                await self._emit(snapshot.market_id)
                    
            logger.info("Replay playback completed.")
        except Exception as e:
            logger.error(f"Error during playback loop: {e}")
            
        self._running = False
