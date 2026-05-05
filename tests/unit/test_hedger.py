import pytest
from parallax.config import settings
from parallax.shared.schemas import Leg
from parallax.execution.hedger import UnwindEngine

@pytest.fixture
def mock_clients(monkeypatch):
    kalshi_orders = []
    poly_orders = []

    async def mock_execute_kalshi(self, leg: Leg):
        kalshi_orders.append(leg)
        return {"status": "unwound", "market": leg.market_id}

    async def mock_execute_poly(self, leg: Leg):
        poly_orders.append(leg)
        return {"status": "unwound", "market": leg.market_id}

    monkeypatch.setattr("parallax.execution.kalshi_execution_client.KalshiExecutionClient.execute_order", mock_execute_kalshi)
    monkeypatch.setattr("parallax.execution.polymarket_execution_client.PolymarketExecutionClient.execute_order", mock_execute_poly)
    
    return kalshi_orders, poly_orders

@pytest.mark.anyio
async def test_unwind_engine_success(mock_clients):
    settings.runtime_auto_unwind_enabled = True
    settings.runtime_max_unwind_slippage = 0.05
    
    kalshi_orders, poly_orders = mock_clients
    
    executed_leg = Leg(
        market_id="K_MKT1",
        outcome="YES",
        price=0.50,
        quantity=100,
        action="BUY",
        side="YES",
        platform="kalshi"
    )
    failed_leg = Leg(
        market_id="P_MKT2",
        outcome="NO",
        price=0.45,
        quantity=100,
        action="BUY",
        side="NO",
        platform="polymarket"
    )

    hedger = UnwindEngine()
    
    # We pass the executed legs that we must dump
    await hedger.handle_partial_fill([executed_leg], [failed_leg], "test_cid")
    
    assert len(kalshi_orders) == 1
    assert len(poly_orders) == 0
    
    unwind_order = kalshi_orders[0]
    assert unwind_order.action == "SELL"
    # Slippage adjustment for sell: 0.50 * 0.95 = 0.475 -> 0.475
    assert unwind_order.price == 0.475
    assert unwind_order.market_id == "K_MKT1"
    
@pytest.mark.anyio
async def test_unwind_engine_disabled(mock_clients):
    settings.runtime_auto_unwind_enabled = False
    
    kalshi_orders, poly_orders = mock_clients
    
    executed_leg = Leg(
        market_id="K_MKT1",
        outcome="YES",
        price=0.50,
        quantity=100,
        action="BUY",
        side="YES",
        platform="kalshi"
    )
    failed_leg = Leg(
        market_id="P_MKT2",
        outcome="NO",
        price=0.45,
        quantity=100,
        action="BUY",
        side="NO",
        platform="polymarket"
    )

    hedger = UnwindEngine()
    await hedger.handle_partial_fill([executed_leg], [failed_leg], "test_cid")
    
    # Unwind disabled, no orders should be sent
    assert len(kalshi_orders) == 0
    assert len(poly_orders) == 0
