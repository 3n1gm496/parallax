import uuid
import pytest
from unittest.mock import AsyncMock

from parallax.execution.executor import ExecutionManager
from parallax.shared.schemas import Leg
from parallax.config import settings

@pytest.mark.anyio
async def test_execution_manager_routing():
    # Setup mocks
    mock_kalshi = AsyncMock()
    mock_kalshi.execute_order.return_value = {"status": "kalshi_ok"}
    
    mock_polymarket = AsyncMock()
    mock_polymarket.execute_order.return_value = {"status": "poly_ok"}

    manager = ExecutionManager()
    manager.kalshi = mock_kalshi
    manager.polymarket = mock_polymarket

    # Enable execution for test
    original_live = settings.runtime_live_execution_enabled
    original_dry = settings.runtime_dry_run
    settings.runtime_live_execution_enabled = True
    settings.runtime_dry_run = False

    try:
        basket_legs = [
            {
                "market_id": "KX123",
                "outcome": "yes",
                "price": 0.40,
                "quantity": 100,
                "side": "YES",
                "platform": "kalshi"
            },
            {
                "market_id": "0x123",
                "outcome": "BUY",
                "price": 0.60,
                "quantity": 100,
                "side": "YES",
                "platform": "polymarket",
                "token_id": "token_abc"
            }
        ]
        
        from unittest.mock import patch
        with patch("anyio.to_thread.run_sync") as mock_thread:
            # We must return a value for intent_id
            mock_thread.return_value = uuid.uuid4()
            report = await manager.execute_basket(basket_legs)
        
        assert "KX123" in report
        assert report["KX123"] == {"status": "kalshi_ok"}
        
        assert "0x123" in report
        assert report["0x123"] == {"status": "poly_ok"}
        
        # Verify calls
        assert mock_kalshi.execute_order.call_count == 1
        kalshi_leg = mock_kalshi.execute_order.call_args[0][0]
        assert isinstance(kalshi_leg, Leg)
        assert kalshi_leg.market_id == "KX123"
        
        assert mock_polymarket.execute_order.call_count == 1
        poly_leg = mock_polymarket.execute_order.call_args[0][0]
        assert isinstance(poly_leg, Leg)
        assert poly_leg.market_id == "0x123"

    finally:
        settings.runtime_live_execution_enabled = original_live
        settings.runtime_dry_run = original_dry
