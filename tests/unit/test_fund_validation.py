import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from parallax.execution.executor import ExecutionManager
from parallax.execution.balance_service import BalanceService
from parallax.shared.schemas import Leg

@pytest.fixture(autouse=True)
def mock_db_session(monkeypatch):
    """Auto-mock database session for all execution tests to avoid PG connection."""
    mock_session = MagicMock()
    # Handle context manager
    mock_session.__enter__.return_value = mock_session
    mock_session_factory = MagicMock(return_value=mock_session)
    
    # Mock the specific path used in executor.py
    monkeypatch.setattr("parallax.db.session.SessionLocal", mock_session_factory)
    return mock_session

@pytest.mark.anyio
async def test_execution_manager_insufficient_funds():
    # Mock clients
    kalshi_mock = AsyncMock()
    kalshi_mock.get_balance.return_value = 10.0 # Only $10
    
    poly_mock = AsyncMock()
    poly_mock.get_balance.return_value = 1000.0 # $1000
    
    # Initialize Manager
    em = ExecutionManager()
    em.kalshi = kalshi_mock
    em.polymarket = poly_mock
    # Re-init balance service with mocks
    em.balance_service = BalanceService(kalshi_mock, poly_mock)
    
    # Basket that requires $50 on Kalshi
    basket = [
        {"market_id": "K1", "platform": "kalshi", "price": 0.5, "quantity": 100, "action": "BUY", "outcome": "YES", "side": "YES"}, # $50
        {"market_id": "P1", "platform": "pm", "price": 0.4, "quantity": 100, "action": "BUY", "outcome": "YES", "side": "YES"}     # $40
    ]
    
    # Execute
    results = await em.execute_basket(basket)
    
    # Should be empty because funds check failed
    assert results == {}
    kalshi_mock.get_balance.assert_called()
    poly_mock.get_balance.assert_called()

@pytest.mark.anyio
async def test_execution_manager_sufficient_funds():
    # Mock clients
    kalshi_mock = AsyncMock()
    kalshi_mock.get_balance.return_value = 100.0
    kalshi_mock.execute_order.return_value = {"status": "ok"}
    
    poly_mock = AsyncMock()
    poly_mock.get_balance.return_value = 1000.0
    poly_mock.execute_order.return_value = {"status": "ok"}
    
    em = ExecutionManager()
    em.kalshi = kalshi_mock
    em.polymarket = poly_mock
    em.balance_service = BalanceService(kalshi_mock, poly_mock)
    
    basket = [
        {"market_id": "K1", "platform": "kalshi", "price": 0.5, "quantity": 10, "action": "BUY", "outcome": "YES", "side": "YES"}, # $5
        {"market_id": "P1", "platform": "pm", "price": 0.4, "quantity": 10, "action": "BUY", "outcome": "YES", "side": "YES"}     # $4
    ]
    
    results = await em.execute_basket(basket)
    
    # Should have executed both
    assert len(results) == 2
    assert results["K1"]["status"] == "ok"
    assert results["P1"]["status"] == "ok"
