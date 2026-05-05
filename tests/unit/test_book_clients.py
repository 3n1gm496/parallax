
import pytest

from parallax.execution.kalshi_book_client import KalshiBookClient
from parallax.execution.polymarket_book_client import PolymarketBookClient
from parallax.execution.schemas import OrderbookSnapshot

@pytest.mark.anyio
async def test_polymarket_delta_application():
    snapshots = []
    async def mock_callback(market_id, snapshot: OrderbookSnapshot):
        snapshots.append((market_id, snapshot))

    client = PolymarketBookClient(mock_callback)
    client.add_markets({"poly_market_1": {"token_id": "token_1", "platform": "polymarket"}})
    
    assert "token_1" in client.books
    
    # 1. Apply a snapshot
    snapshot_data = {
        "event_type": "book",
        "asset_id": "token_1",
        "bids": [{"price": "0.40", "size": "100"}, {"price": "0.39", "size": "200"}],
        "asks": [{"price": "0.42", "size": "100"}],
        "timestamp": "1700000000000"
    }
    client._handle_book_update("token_1", snapshot_data, is_snapshot=True)
    await client._emit_snapshot("token_1", snapshot_data.get("timestamp"))
    
    assert len(snapshots) == 1
    m_id, snap = snapshots[-1]
    assert m_id == "poly_market_1"
    assert snap.bids.levels[0].price == 0.40
    assert snap.bids.levels[0].size == 100
    assert snap.asks.levels[0].price == 0.42
    
    # 2. Apply a delta that removes a level and adds a new one
    delta_data = {
        "event_type": "price_change",
        "asset_id": "token_1",
        "bids": [{"price": "0.40", "size": "0"}], # remove 0.40
        "asks": [{"price": "0.41", "size": "50"}],  # add 0.41
        "timestamp": "1700000001000"
    }
    client._handle_book_update("token_1", delta_data, is_snapshot=False)
    await client._emit_snapshot("token_1", delta_data.get("timestamp"))
    
    m_id, snap = snapshots[-1]
    assert len(snap.bids.levels) == 1
    assert snap.bids.levels[0].price == 0.39
    
    assert len(snap.asks.levels) == 2
    assert snap.asks.levels[0].price == 0.41
    assert snap.asks.levels[1].price == 0.42

@pytest.mark.anyio
async def test_kalshi_delta_application():
    snapshots = []
    async def mock_callback(market_id, snapshot: OrderbookSnapshot):
        snapshots.append((market_id, snapshot))

    client = KalshiBookClient(mock_callback)
    client.add_markets({"kalshi_market_1": {"ticker": "KX123", "platform": "kalshi"}})
    
    assert "KX123" in client.books
    
    # 1. Apply a snapshot
    snapshot_data = {
        "type": "orderbook_snapshot",
        "market_ticker": "KX123",
        "yes_bid_levels": [[40, 100], [39, 200]], # 40 cents, size 100
        "yes_ask_levels": [[42, 100]],
        "ts": 1700000000000
    }
    client._handle_snapshot(snapshot_data)
    await client._emit_snapshot("KX123", snapshot_data.get("ts"))
    
    m_id, snap = snapshots[-1]
    assert m_id == "KX123" # Ticker is used as ID here
    assert snap.bids.levels[0].price == 0.40
    assert snap.asks.levels[0].price == 0.42
    
    # 2. Apply a delta removing a level
    delta_data_1 = {
        "type": "orderbook_delta",
        "market_ticker": "KX123",
        "price": 40,
        "quantity": 0,
        "side": "yes_bid",
        "ts": 1700000001000
    }
    client._handle_delta(delta_data_1)
    await client._emit_snapshot("KX123", delta_data_1.get("ts"))
    
    m_id, snap = snapshots[-1]
    assert len(snap.bids.levels) == 1
    assert snap.bids.levels[0].price == 0.39
    
    # 3. Apply a delta adding/updating a level
    delta_data_2 = {
        "type": "orderbook_delta",
        "market_ticker": "KX123",
        "price": 41,
        "quantity": 50,
        "side": "yes_ask",
        "ts": 1700000002000
    }
    client._handle_delta(delta_data_2)
    await client._emit_snapshot("KX123", delta_data_2.get("ts"))
    
    m_id, snap = snapshots[-1]
    assert len(snap.asks.levels) == 2
    assert snap.asks.levels[0].price == 0.41
    assert snap.asks.levels[0].size == 50
