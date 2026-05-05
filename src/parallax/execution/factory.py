from parallax.config import settings
from parallax.execution.streamer import BaseStreamer, OrderbookStreamer
from parallax.execution.replay_streamer import ReplayStreamer
from parallax.execution.recorder import OrderbookRecorder

def create_streamer() -> BaseStreamer:
    """
    Creates and returns the appropriate streamer based on configuration.
    If recording mode is enabled, it attaches the recorder to the live streamer.
    """
    if settings.runtime_replay_mode:
        return ReplayStreamer()
    
    streamer = OrderbookStreamer()
    
    if settings.runtime_recording_mode:
        recorder = OrderbookRecorder()
        # Ensure recorder starts when streamer starts
        original_start = streamer.start
        original_stop = streamer.stop
        
        async def start_with_recorder(market_registry):
            await recorder.start()
            async def recorder_callback(market_id: str):
                snapshot = streamer.orderbooks.get(market_id)
                if snapshot:
                    await recorder.on_snapshot(market_id, snapshot)
            streamer.subscribe(recorder_callback)
            await original_start(market_registry)
            
        async def stop_with_recorder():
            await original_stop()
            await recorder.stop()
            
        streamer.start = start_with_recorder
        streamer.stop = stop_with_recorder
        
    return streamer
