import os
import logging
from datetime import datetime, timezone
import anyio

from parallax.execution.schemas import OrderbookSnapshot

logger = logging.getLogger(__name__)

class OrderbookRecorder:
    """
    Listens to OrderbookSnapshot updates and writes them to a JSONL file.
    This provides raw tick data for the Replay Engine.
    """
    
    def __init__(self, output_dir: str = "data/replays"):
        self.output_dir = output_dir
        self._file_path = None
        self._file_handle = None
        
    async def start(self):
        await anyio.Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._file_path = os.path.join(self.output_dir, f"replay_{timestamp}.jsonl")
        
        logger.info(f"Starting OrderbookRecorder, writing to {self._file_path}")
        # anyio file I/O
        path = anyio.Path(self._file_path)
        self._file_handle = await path.open(mode="a")
        
    async def stop(self):
        if self._file_handle:
            await self._file_handle.aclose()
            logger.info(f"Stopped OrderbookRecorder. Saved to {self._file_path}")
            self._file_handle = None

    def get_file_path(self) -> str | None:
        return self._file_path

    async def on_snapshot(self, market_id: str, snapshot: OrderbookSnapshot):
        if not self._file_handle:
            return
            
        try:
            # We dump the snapshot to json and write to file
            json_str = snapshot.model_dump_json()
            await self._file_handle.write(json_str + "\n")
        except Exception as e:
            logger.error(f"Failed to record snapshot for {market_id}: {e}")

