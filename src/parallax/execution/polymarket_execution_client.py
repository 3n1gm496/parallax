import logging

from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, Side

from parallax.config import settings
from parallax.shared.schemas import Leg

logger = logging.getLogger(__name__)

class PolymarketExecutionClient:
    """Client for placing orders on Polymarket CLOB via py-clob-client-v2."""

    def __init__(self):
        self._key = settings.polymarket_private_key
        self._funder = settings.polymarket_funder
        self._chain_id = settings.polymarket_chain_id
        
        self.client = None
        
        if self._key:
            try:
                sig_type = 1 if self._funder else 0
                
                # Initialize client for L1 Auth
                auth_client = ClobClient(
                    host="https://clob.polymarket.com",
                    chain_id=self._chain_id,
                    key=self._key,
                    signature_type=sig_type,
                    funder=self._funder if self._funder else None
                )
                
                creds = auth_client.create_or_derive_api_creds()
                
                # Main client with L2 Auth
                self.client = ClobClient(
                    host="https://clob.polymarket.com",
                    chain_id=self._chain_id,
                    key=self._key,
                    creds=creds,
                    signature_type=sig_type,
                    funder=self._funder if self._funder else None
                )
                logger.info("Polymarket CLOB client authenticated.")
            except Exception as e:
                logger.error(f"Failed to initialize Polymarket CLOB client: {e}")
        else:
            logger.warning("No Polymarket private key provided. Cannot execute real orders.")

    async def get_balance(self) -> float | None:
        """Fetches the USDC balance of the associated funder/wallet."""
        if settings.runtime_dry_run:
            return 1000.0
            
        if not self.client:
            return None
            
        try:
            # We fetch the balance of the proxy or funder
            address = self._funder or self.client.get_address()
            if not address:
                return None
                
            # py-clob-client has a method to get balance
            balance_info = self.client.get_balance(address)
            if balance_info:
                return float(balance_info.get("balance", 0))
            return None
        except Exception as e:
            logger.error(f"Failed to get Polymarket balance: {e}")
            return None

    async def execute_order(self, leg: Leg) -> dict | None:
        """
        Submits an order to Polymarket.
        Uses FOK (Fill-Or-Kill) logic by default.
        """
        if settings.runtime_dry_run:
            logger.info(f"[DRY RUN] Polymarket execute: token={leg.token_id} qty={leg.quantity} price={leg.price}")
            return {"status": "dry_run_success", "orderID": "mock_poly_order"}

        if not self.client:
            logger.error("Polymarket client not authenticated.")
            return None

        if not leg.token_id:
            logger.error(f"Polymarket execution requires token_id. Missing for {leg.market_id}")
            return None

        try:
            side = Side.BUY if leg.action.upper() == "BUY" else Side.SELL
            
            order_args = OrderArgs(
                token_id=leg.token_id,
                price=round(leg.price, 3), # CLOB typically uses 3 decimal places for price
                side=side,
                size=round(leg.quantity, 2)
            )

            # [LOGIC FIX] Wrap synchronous CLOB call in to_thread to avoid blocking
            import anyio
            
            def _post():
                return self.client.create_and_post_order(
                    order_args=order_args,
                    order_type=OrderType.FOK
                )

            resp = await anyio.to_thread.run_sync(_post)
            
            if resp.get("success"):
                logger.info(f"Polymarket order successful: {resp}")
                return resp
            else:
                logger.error(f"Polymarket order failed: {resp.get('errorMsg')}")
                return None
        except Exception as e:
            logger.error(f"Polymarket execution error: {e}")
            return None
