import logging
from typing import Optional
import parallax_core
from parallax.execution.schemas import OrderbookSnapshot

logger = logging.getLogger(__name__)

class L1HotCache:
    """
    [PHASE 3] L1 Hot Cache: Optimized wrapper around the Rust OrderbookManager.
    Offloads all price-level processing to Rust and enables ultra-fast
    lookups for the discovery pipeline.
    """
    _instance: Optional['L1HotCache'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(L1HotCache, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.manager = parallax_core.OrderbookManager()
        self._update_counts: dict[str, int] = {} # market_id -> count in window
        self._last_reset = time.time()
        self._initialized = True
        logger.info("L1HotCache initialized (Rust-backed with Volatility Tracking)")

    def update_from_snapshot(self, snapshot: OrderbookSnapshot):
        """
        [PHASE 4] Pushes an entire snapshot to Rust and tracks volatility.
        """
        try:
            m_id = snapshot.market_id
            venue = snapshot.platform
            
            # Track volatility (updates per reset window)
            self._update_counts[m_id] = self._update_counts.get(m_id, 0) + 1
            
            # Reset window every 10s
            now = time.time()
            if now - self._last_reset > 10.0:
                self._update_counts = {m_id: 1} # Start new window
                self._last_reset = now

            self.manager.batch_update_bids(m_id, venue, [(lv.price, lv.size) for lv in snapshot.bids.levels])
            self.manager.batch_update_asks(m_id, venue, [(lv.price, lv.size) for lv in snapshot.asks.levels])
        except Exception as e:
            logger.error(f"L1Cache batch update failed for {snapshot.market_id}: {e}")

    def get_volatility_score(self, market_id: str) -> float:
        """
        Returns a score (0.0 to 1.0) representing current volatility.
        > 10 updates in 10s is considered high.
        """
        count = self._update_counts.get(market_id, 0)
        return min(1.0, count / 20.0) # Normalized to 20 updates/10s

    def get_orderbook(self, market_id: str) -> Optional[parallax_core.Orderbook]:
        """
        Returns a snapshot of the current Rust orderbook.
        """
        return self.manager.get_book(market_id)

    def get_best_prices(self, market_id: str) -> tuple[Optional[float], Optional[float]]:
        """
        Returns (best_bid, best_ask) directly from Rust.
        """
        book = self.get_orderbook(market_id)
        if not book:
            return None, None
        
        bb = book.best_bid()
        ba = book.best_ask()
        return (bb[0] if bb else None, ba[0] if ba else None)
