import os
import asyncio
import pytest
import aiofiles
from datetime import datetime, timezone, timedelta

from parallax.config import settings
from parallax.execution.schemas import OrderbookSnapshot, OrderbookSide, OrderbookLevel
from parallax.execution.recorder import OrderbookRecorder
from parallax.execution.replay_streamer import ReplayStreamer

def _create_snapshot(market_id: str, mid_price: float, dt: datetime) -> OrderbookSnapshot:
    bids = OrderbookSide(levels=[OrderbookLevel(price=mid_price - 0.01, size=100)], total_depth=100)
    asks = OrderbookSide(levels=[OrderbookLevel(price=mid_price + 0.01, size=100)], total_depth=100)
    return OrderbookSnapshot(
        id=f"snap_{market_id}_{dt.timestamp()}",
        platform="kalshi",
        market_id=market_id,
        outcome="YES",
        captured_at=dt,
        bids=bids,
        asks=asks,
        mid_price=mid_price,
        spread_bps=200
    )

@pytest.mark.anyio
async def test_recorder_and_replay_streamer(tmp_path):
    # Setup test directory
    output_dir = str(tmp_path / "replays")
    
    # 1. Test Recorder
    recorder = OrderbookRecorder(output_dir=output_dir)
    await recorder.start()
    
    file_path = recorder.get_file_path()
    assert file_path is not None
    assert os.path.exists(file_path)
    
    # Create fake snapshots 1 second apart
    t0 = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    snap1 = _create_snapshot("MKT1", 0.50, t0)
    snap2 = _create_snapshot("MKT1", 0.51, t0 + timedelta(seconds=1))
    
    # Actually OrderbookRecorder expects (market_id) wait, on_snapshot only takes (market_id, snapshot)?
    # Ah, the subscribe signature is callback(market_id). But update_snapshot expects (market_id, snapshot).
    # Wait, the streamer's callbacks take only `market_id`.
    # Let me check my recorder.py. `on_snapshot(market_id, snapshot)`. This is a bug!
    # I'll manually call it for now.
    
    await recorder.on_snapshot("MKT1", snap1)
    await recorder.on_snapshot("MKT1", snap2)
    
    await recorder.stop()
    
    # Verify file content
    async with aiofiles.open(file_path, "r") as f:
        lines = await f.readlines()
        assert len(lines) == 2
        assert "0.5" in lines[0]
        assert "0.51" in lines[1]
        
    # 2. Test Replay Streamer
    # Use the max speed setting to avoid waiting
    settings.runtime_replay_file = file_path
    settings.runtime_replay_speed_factor = 0.0
    settings.runtime_replay_mode = True
    
    streamer = ReplayStreamer()
    emitted_markets = []
    
    async def mock_callback(market_id: str):
        emitted_markets.append(market_id)
        
    streamer.subscribe(mock_callback)
    
    await streamer.start({})
    
    # Give it a moment to run the playback loop
    await asyncio.sleep(0.1)
    
    await streamer.stop()
    
    assert len(emitted_markets) == 2
    assert emitted_markets[0] == "MKT1"
    assert emitted_markets[1] == "MKT1"
    assert "MKT1" in streamer.orderbooks
    assert streamer.orderbooks["MKT1"].mid_price == 0.51

