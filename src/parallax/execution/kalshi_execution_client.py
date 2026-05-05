import base64
import json
import logging
import time
import uuid

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from parallax.config import settings
from parallax.shared.schemas import Leg

logger = logging.getLogger(__name__)

class KalshiExecutionClient:
    """Client for placing authenticated orders on Kalshi Trade API v2."""

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client
        self._base_url = "https://api.elections.kalshi.com/trade-api/v2"

    async def execute_order(self, leg: Leg) -> dict | None:
        """
        Submits an order to Kalshi.
        Uses FOK (Fill-Or-Kill) or IOC (Immediate-Or-Cancel) logic by default.
        """
        if settings.runtime_dry_run:
            logger.info(f"[DRY RUN] Kalshi execute: {leg.market_id} {leg.outcome} qty={leg.quantity} price={leg.price}")
            return {"status": "dry_run_success", "client_order_id": str(uuid.uuid4())}

        # Determine price in cents
        price_cents = int(round(leg.price * 100))
        if price_cents <= 0 or price_cents >= 100:
            logger.error(f"Invalid Kalshi price for {leg.market_id}: {leg.price}")
            return None

        # Convert size to integer count
        count = int(round(leg.quantity))
        if count <= 0:
            logger.error(f"Invalid Kalshi count for {leg.market_id}: {leg.quantity}")
            return None

        # Kalshi usually trades "YES" or "NO"
        side = leg.outcome.lower() if leg.outcome else leg.side.lower()
        if side not in ("yes", "no"):
            side = "yes"  # Default fallback, though should match outcome

        action = leg.action.lower()
        
        payload = {
            "ticker": leg.market_id,
            "action": action,
            "side": side,
            "type": "limit",
            "count": count,
            "yes_price": price_cents if side == "yes" else (100 - price_cents),
            "client_order_id": str(uuid.uuid4()),
            "time_in_force": "ioc"  # Use Immediate-Or-Cancel
        }

        path = "/trade-api/v2/portfolio/orders"
        headers = self._get_auth_headers("POST", path, payload)
        
        if not headers:
            logger.error("Failed to generate Kalshi auth headers.")
            return None

        client = self._client or httpx.AsyncClient(timeout=10.0)
        own_client = self._client is None
        try:
            resp = await client.post(
                f"{self._base_url}/portfolio/orders",
                json=payload,
                headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Kalshi order successful: {data}")
            return data
        except httpx.HTTPStatusError as e:
            logger.error(f"Kalshi execution HTTP error: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Kalshi execution error: {e}")
            return None
        finally:
            if own_client:
                await client.aclose()

    def _get_auth_headers(self, method: str, path: str, payload: dict | None = None) -> dict | None:
        api_key_id = settings.kalshi_api_key
        private_key_str = settings.kalshi_api_secret
        
        if not api_key_id or not private_key_str:
            return None
            
        try:
            if "-----BEGIN" not in private_key_str:
                private_key_str = f"-----BEGIN PRIVATE KEY-----\n{private_key_str}\n-----END PRIVATE KEY-----"
                
            private_key = serialization.load_pem_private_key(
                private_key_str.encode('utf-8'),
                password=None,
            )
            
            timestamp = str(int(time.time() * 1000))
            msg_string = timestamp + method + path
            
            if payload:
                # Add stringified payload to the message signature payload for Kalshi V2 POST
                # The Kalshi API documentation might require body payload stringification.
                msg_string += json.dumps(payload, separators=(',', ':'))

            signature = private_key.sign(
                msg_string.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            return {
                "KALSHI-ACCESS-KEY": api_key_id,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "KALSHI-ACCESS-SIGNATURE": signature_b64,
                "Content-Type": "application/json"
            }
        except Exception as e:
            logger.error(f"Failed to generate Kalshi auth headers: {e}")
            return None
