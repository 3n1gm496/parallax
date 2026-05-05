# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/cache/aerospike_adapter.py
#
# Aerospike L3 cache adapter (Production deployment only).
# In development, this layer is a no-op. In production with Aerospike installed:
#   1. Set AEROSPIKE_HOST and AEROSPIKE_PORT in .env
#   2. `uv add aerospike`
#   3. Run: docker run -d -p 3000:3000 aerospike/aerospike-server
#
# Why Aerospike:
#   - Hybrid Memory Architecture (RAM + NVMe SSD as extended RAM)
#   - Sub-millisecond reads regardless of data size
#   - Cluster-native: survives node failures without data loss
#   - Used by fintech firms for real-time risk and order management
#
# In the Parallax architecture, Aerospike acts as the "bridge" that allows
# multiple Python worker processes AND the future Rust subprocess to share
# compiled arbitrage state without going through the database.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_client = None


def get_aerospike_client():
    """
    Return a singleton Aerospike client.
    Returns None if Aerospike is not configured or the package is missing.
    Offline-safe: callers must handle None.
    """
    global _client
    if _client is not None:
        return _client

    from parallax.config import settings
    host = getattr(settings, "aerospike_host", "")
    port = int(getattr(settings, "aerospike_port", 3000))

    if not host:
        return None

    try:
        import aerospike  # type: ignore[import]
        config = {"hosts": [(host, port)]}
        _client = aerospike.client(config).connect()
        logger.info(f"✅  Aerospike connected → {host}:{port}")
    except ImportError:
        logger.info("Aerospike package not installed — L3 cache disabled.")
        _client = None
    except Exception as exc:
        logger.warning(f"Aerospike connection failed ({exc}) — L3 cache disabled.")
        _client = None

    return _client


class AerospikeAdapter:
    """
    Thin wrapper around the Aerospike client for HotCache L3 writes/reads.
    All methods are offline-safe (no-ops when client is None).

    Namespace: "parallax"
    Set:       "arb_sets"
    Key:       set_id (str)
    Bins:      { "data": <JSON blob>, "edge_bps": float, "expires_at": str }
    """

    NAMESPACE = "parallax"
    SET       = "arb_sets"
    TTL_S     = 3600  # Aerospike server-side TTL

    def write(self, set_id: str, payload: dict) -> bool:
        client = get_aerospike_client()
        if not client:
            return False
        try:
            import aerospike as _aerospike  # type: ignore[import]
            record_key = (self.NAMESPACE, self.SET, set_id)
            bins = {
                "data":     json.dumps(payload, separators=(",", ":")),
                "edge_bps": float(payload.get("edge_bps", 0.0)),
                "fingerprint": payload.get("fingerprint", ""),
            }
            meta = {"ttl": self.TTL_S}
            policy = {"exists": _aerospike.POLICY_EXISTS_CREATE_OR_REPLACE}
            client.put(record_key, bins, meta, policy)
            return True
        except Exception as exc:
            logger.debug(f"Aerospike write error: {exc}")
            return False

    def read(self, set_id: str, expected_fingerprint: str | None = None) -> dict | None:
        client = get_aerospike_client()
        if not client:
            return None
        try:
            key = (self.NAMESPACE, self.SET, set_id)
            _, _, bins = client.get(key)
            if bins and "data" in bins:
                if expected_fingerprint and bins.get("fingerprint") != expected_fingerprint:
                    logger.warning(f"Aerospike: fingerprint mismatch for {set_id}. Purging.")
                    self.delete(set_id)
                    return None
                return json.loads(bins["data"])
            return None
        except Exception as exc:
            logger.debug(f"Aerospike read error: {exc}")
            return None

    def delete(self, set_id: str) -> bool:
        client = get_aerospike_client()
        if not client:
            return False
        try:
            key = (self.NAMESPACE, self.SET, set_id)
            client.remove(key)
            return True
        except Exception:
            return False

    def scan_all(self) -> list[dict]:
        """Returns all active arb sets from Aerospike (for cache warming on startup)."""
        client = get_aerospike_client()
        if not client:
            return []
        results = []
        try:
            scan = client.scan(self.NAMESPACE, self.SET)
            for _, _, bins in scan.results():
                if bins and "data" in bins:
                    try:
                        results.append(json.loads(bins["data"]))
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug(f"Aerospike scan error: {exc}")
        return results
