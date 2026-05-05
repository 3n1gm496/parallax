"""
Parallax Hot Cache — Unit Tests

Tests the tiered hot cache (L1 dict + L2 shared memory) without
requiring Aerospike or Neo4j.

Run: uv run pytest tests/unit/test_hot_cache.py -v
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from parallax.cache.schemas import CachedLeg, CompiledArbitrageSet
from parallax.cache.hot_cache import HotCache, compile_from_graph


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_set(
    market_a: str = "K-TRUMP",
    market_b: str = "P-TRUMP",
    edge_bps: float = 400.0,
    expires_in_s: int = 3600,
) -> CompiledArbitrageSet:
    now = datetime.now(timezone.utc)
    legs = [
        CachedLeg(market_id=market_a, platform="kalshi",    side="YES", action="BUY", token_id=None, max_price=0.48, target_size=100.0),
        CachedLeg(market_id=market_b, platform="polymarket", side="NO",  action="BUY", token_id=None, max_price=0.48, target_size=100.0),
    ]
    return CompiledArbitrageSet(
        set_id=str(uuid.uuid4()),
        legs=legs,
        expected_edge_bps=edge_bps,
        min_confidence=0.92,
        compiled_at=now,
        expires_at=now + timedelta(seconds=expires_in_s),
        source="test",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHotCacheL1:
    """Test L1 (in-process dict) layer."""

    def setup_method(self):
        """Reset singleton for each test."""
        HotCache._instance = None

    def test_put_and_get(self):
        cache = HotCache.instance()
        arb = _make_set()
        cache.put(arb)

        result = cache.get(arb.set_id)
        assert result is not None
        assert result.set_id == arb.set_id

    def test_get_by_market_reverse_index(self):
        cache = HotCache.instance()
        arb = _make_set(market_a="K-TRUMP-2024", market_b="P-TRUMP-2024")
        cache.put(arb)

        # Should find by either leg
        sets_a = cache.get_by_market("K-TRUMP-2024")
        sets_b = cache.get_by_market("P-TRUMP-2024")

        assert any(s.set_id == arb.set_id for s in sets_a)
        assert any(s.set_id == arb.set_id for s in sets_b)

    def test_expired_set_not_returned(self):
        cache = HotCache.instance()
        arb_expired = _make_set(expires_in_s=-1)  # Already expired
        cache.put(arb_expired)

        result = cache.get(arb_expired.set_id)
        assert result is None, "Expired set should not be returned"

        sets = cache.get_by_market("K-TRUMP")
        assert not any(s.set_id == arb_expired.set_id for s in sets)

    def test_invalidate(self):
        cache = HotCache.instance()
        arb = _make_set()
        cache.put(arb)
        cache.invalidate(arb.set_id)

        assert cache.get(arb.set_id) is None

    def test_stats(self):
        cache = HotCache.instance()
        valid = _make_set()
        expired = _make_set(expires_in_s=-1)
        cache.put(valid)
        cache.put(expired)

        stats = cache.stats()
        assert stats["total_sets"] == 2
        assert stats["valid_sets"] == 1
        assert stats["expired_sets"] == 1

    def test_is_valid_property(self):
        valid_set = _make_set(edge_bps=400.0, expires_in_s=3600)
        expired_set = _make_set(edge_bps=400.0, expires_in_s=-1)
        no_edge_set = _make_set(edge_bps=-10.0, expires_in_s=3600)

        assert valid_set.is_valid
        assert not expired_set.is_valid
        assert not no_edge_set.is_valid


class TestHotCacheL2SharedMemory:
    """Test L2 (shared memory) layer."""

    def setup_method(self):
        HotCache._instance = None

    def test_shm_initialized(self):
        cache = HotCache.instance()
        # Shared memory should be available on Linux
        assert cache.stats()["shm_available"] is True

    def test_shm_mirror_roundtrip(self):
        cache = HotCache.instance()
        arb = _make_set(market_a="K-SHM-A", market_b="P-SHM-B", edge_bps=600.0)
        cache.put(arb)
        time.sleep(0.1)  # Allow mirror thread to run

        shm_data = cache.read_from_shm()
        assert isinstance(shm_data, list)
        ids = [d.get("set_id") for d in shm_data]
        assert arb.set_id in ids


class TestCompileFromGraph:
    """Test the factory function that converts Neo4j output to CompiledArbitrageSet."""

    def test_basic_compilation(self):
        raw = {
            "set_id": str(uuid.uuid4()),
            "market_a_id": "K-BIDEN",
            "market_b_id": "P-BIDEN",
            "confidence": 0.95,
        }
        compiled = compile_from_graph(
            raw, kalshi_price=0.46, poly_price=0.46, target_size=200.0
        )
        assert compiled.expected_edge_bps == pytest.approx(800.0, abs=0.01)
        assert compiled.is_valid
        assert len(compiled.legs) == 2

    def test_rust_args_structure(self):
        raw = {"set_id": "x", "market_a_id": "K-X", "market_b_id": "P-X", "confidence": 0.9}
        compiled = compile_from_graph(raw, kalshi_price=0.46, poly_price=0.46)
        args = compiled.to_rust_args()

        assert "a_ask" in args
        assert "b_ask" in args
        assert args["a_ask"] == pytest.approx(0.46)
        assert args["b_ask"] == pytest.approx(0.46)
