import anyio
import time
import logging
from parallax.execution.replay_streamer import ReplayStreamer
from parallax.config import settings

# Configure logging to see performance metrics
logging.basicConfig(level=logging.INFO)

async def benchmark():
    # Force settings for benchmark
    settings.runtime_replay_file = "mock_replay.jsonl"
    settings.runtime_replay_speed_factor = 0 # Max speed
    
    streamer = ReplayStreamer()
    
    ticks_received = 0
    
    async def on_tick(market_id):
        nonlocal ticks_received
        ticks_received += 1
        
    streamer.subscribe(on_tick)
    
    print(f"Starting benchmark on {settings.runtime_replay_file}...")
    
    start_t = time.perf_counter()
    
    # We use start() which calls prefetch_all()
    await streamer.start({})
    
    # Wait for completion (the streamer will set _running = False when done)
    while streamer._running:
        await anyio.sleep(0.1)
        
    await streamer.stop()
    
    elapsed = time.perf_counter() - start_t
    print("-" * 30)
    print(f"Benchmark Results:")
    print(f"Total Ticks: {ticks_received}")
    print(f"Total Time:  {elapsed:.4f}s")
    print(f"Throughput:  {ticks_received/elapsed:.0f} ticks/s")
    print("-" * 30)

if __name__ == "__main__":
    anyio.run(benchmark)
