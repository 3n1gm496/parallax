# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/cache/hot_cache.py
#
# Parallax V2 — Tiered Hot Cache
#
# Architecture (LMAX Disruptor-inspired, adapted for Python/Rust hybrid):
#
#   ┌──────────────────────────────────────────────────────────────┐
#   │  Cold Path (Neo4j / SemanticAgent)                          │
#   │     compiles ArbitrageSet objects                           │
#   └───────────────────────┬──────────────────────────────────────┘
#                           │ HotCache.put()
#   ┌───────────────────────▼──────────────────────────────────────┐
#   │  L1 Cache — Python dict (in-process, ~20ns lookup)          │
#   │  { set_id → CompiledArbitrageSet }                          │
#   │  { market_id → [set_id, ...] }  ← fast reverse index       │
#   └───────────────────────┬──────────────────────────────────────┘
#                           │ async mirror (non-blocking)
#   ┌───────────────────────▼──────────────────────────────────────┐
#   │  L2 Cache — multiprocessing.shared_memory (cross-process)   │
#   │  JSON-serialised ring buffer, ~500ns lookup                 │
#   │  Allows the Rust subprocess (future) to read with mmap      │
#   └───────────────────────┬──────────────────────────────────────┘
#                           │ adapter (production only)
#   ┌───────────────────────▼──────────────────────────────────────┐
#   │  L3 Cache — Aerospike (optional, distributed, <1ms)         │
#   │  Activated by setting AEROSPIKE_HOST in .env               │
#   └──────────────────────────────────────────────────────────────┘
#
# The StreamScanner reads from L1 only (sub-microsecond).
# Writes propagate L1 → L2 → L3 asynchronously.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from multiprocessing.shared_memory import SharedMemory
from typing import Iterator

from parallax.cache.schemas import CachedLeg, CompiledArbitrageSet

logger = logging.getLogger(__name__)

# Shared memory block name and size (must be fixed at startup)
_SHM_NAME   = "parallax_hotcache_v2"
_SHM_BYTES  = 2 * 1024 * 1024   # 2 MB — holds ~500 compiled sets as JSON
_DEFAULT_TTL_SECONDS = 3600      # Sets expire after 1 hour by default


class HotCache:
    """
    Singleton in-memory hot cache for compiled arbitrage sets.

    Thread-safe reads (via RWLock pattern using threading.Lock).
    Async-compatible writes (write() calls are fire-and-forget via asyncio.create_task).

    Usage:
        cache = HotCache.instance()
        cache.put(compiled_set)
        sets = cache.get_by_market("TRUMP-2024-YES")
    """

    _instance: HotCache | None = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> "HotCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        # L1: primary in-process store
        self._store: dict[str, CompiledArbitrageSet] = {}
        # Reverse index: market_id → set_ids
        self._market_index: dict[str, list[str]] = defaultdict(list)
        self._rw_lock = threading.RLock()

        # L2: shared memory (best effort — disabled if unavailable)
        self._shm: SharedMemory | None = None
        self._init_shared_memory()

        # Background TTL eviction
        self._eviction_thread = threading.Thread(
            target=self._eviction_loop, daemon=True, name="HotCache-Eviction"
        )
        self._eviction_thread.start()
        logger.info("⚡ HotCache V2 initialized (L1=dict, L2=shm, eviction=active)")

    # ── Public API ─────────────────────────────────────────────────────────────

    def put(
        self,
        arb_set: CompiledArbitrageSet,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        """
        Store a compiled arbitrage set.
        L1 write is synchronous and immediate (<1μs).
        L2 mirror is deferred.
        """
        with self._rw_lock:
            self._store[arb_set.set_id] = arb_set
            for mid in arb_set.market_ids:
                if arb_set.set_id not in self._market_index[mid]:
                    self._market_index[mid].append(arb_set.set_id)
        # Mirror to L2 asynchronously (best effort, never blocks execution)
        threading.Thread(target=self._mirror_to_shm, daemon=True).start()

    def get(self, set_id: str) -> CompiledArbitrageSet | None:
        with self._rw_lock:
            entry = self._store.get(set_id)
        if entry and entry.is_valid:
            return entry
        return None

    def get_by_market(self, market_id: str) -> list[CompiledArbitrageSet]:
        """
        Fast reverse lookup: given a market_id, return all valid compiled sets
        that include that market. Called on every tick by StreamScanner.
        Average cost: ~2μs (single dict + list lookup with validity filter).
        """
        with self._rw_lock:
            set_ids = list(self._market_index.get(market_id, []))
        return [s for sid in set_ids if (s := self._store.get(sid)) and s.is_valid]

    def get_all_valid(self) -> Iterator[CompiledArbitrageSet]:
        with self._rw_lock:
            items = list(self._store.values())
        return (s for s in items if s.is_valid)

    def invalidate(self, set_id: str) -> None:
        with self._rw_lock:
            entry = self._store.pop(set_id, None)
            if entry:
                for mid in entry.market_ids:
                    try:
                        self._market_index[mid].remove(set_id)
                    except ValueError:
                        pass

    def stats(self) -> dict:
        with self._rw_lock:
            total = len(self._store)
            valid = sum(1 for s in self._store.values() if s.is_valid)
        return {
            "total_sets": total,
            "valid_sets": valid,
            "expired_sets": total - valid,
            "indexed_markets": len(self._market_index),
            "shm_available": self._shm is not None,
        }

    # ── L2: Shared Memory ──────────────────────────────────────────────────────

    def _init_shared_memory(self) -> None:
        try:
            try:
                self._shm = SharedMemory(name=_SHM_NAME, create=False, size=_SHM_BYTES)
                logger.debug("Attached to existing shared memory block.")
            except FileNotFoundError:
                self._shm = SharedMemory(name=_SHM_NAME, create=True, size=_SHM_BYTES)
                # Zero-initialise
                self._shm.buf[:4] = b'\x00\x00\x00\x00'
                logger.info(f"✅  Shared memory created: '{_SHM_NAME}' ({_SHM_BYTES // 1024}KB)")
        except Exception as exc:
            logger.warning(f"Shared memory unavailable ({exc}) — L2 cache disabled.")
            self._shm = None

    def _mirror_to_shm(self) -> None:
        """
        Serialises the entire L1 cache to shared memory as a compact JSON blob.
        Prefixed with a 4-byte little-endian uint32 length header.
        Other processes (or the Rust subprocess) can read this zero-copy.
        """
        if not self._shm:
            return
        try:
            with self._rw_lock:
                payload = [
                    {
                        "set_id": s.set_id,
                        "legs": [
                            {
                                "market_id": leg.market_id,
                                "platform": leg.platform,
                                "side": leg.side,
                                "action": leg.action,
                                "max_price": leg.max_price,
                                "target_size": leg.target_size,
                            }
                            for leg in s.legs
                        ],
                        "edge_bps": s.expected_edge_bps,
                        "expires_at": s.expires_at.isoformat(),
                    }
                    for s in self._store.values()
                    if s.is_valid
                ]
            blob = json.dumps(payload, separators=(",", ":")).encode()
            size = len(blob)
            if size + 4 > _SHM_BYTES:
                logger.warning("Hot cache too large for shared memory block — truncating.")
                blob = blob[:_SHM_BYTES - 4]
                size = len(blob)
            # Write 4-byte length header + payload
            import struct
            self._shm.buf[:4]         = struct.pack("<I", size)
            self._shm.buf[4:4 + size] = blob
        except Exception as exc:
            logger.debug(f"SHM mirror error: {exc}")

    def read_from_shm(self) -> list[dict]:
        """
        Read the shared memory snapshot (called by external processes or Rust).
        Returns the deserialized list of valid sets.
        """
        if not self._shm:
            return []
        try:
            import struct
            size = struct.unpack("<I", bytes(self._shm.buf[:4]))[0]
            if size == 0 or size > _SHM_BYTES - 4:
                return []
            blob = bytes(self._shm.buf[4:4 + size])
            return json.loads(blob)
        except Exception as exc:
            logger.debug(f"SHM read error: {exc}")
            return []

    def close_shm(self) -> None:
        if self._shm:
            try:
                self._shm.close()
                self._shm.unlink()
            except Exception:
                pass

    # ── TTL Eviction ───────────────────────────────────────────────────────────

    def _eviction_loop(self) -> None:
        while True:
            time.sleep(60)  # Check every minute
            now = datetime.now(timezone.utc)
            with self._rw_lock:
                expired = [
                    sid for sid, s in self._store.items()
                    if now >= s.expires_at
                ]
            for sid in expired:
                self.invalidate(sid)
            if expired:
                logger.debug(f"HotCache evicted {len(expired)} expired sets.")


# ─────────────────────────────────────────────────────────────────────────────
# Factory: build a CompiledArbitrageSet from a Neo4j ArbitrageSet dict
# ─────────────────────────────────────────────────────────────────────────────

def compile_from_graph(
    arb_graph_dict: dict,
    *,
    kalshi_price: float,
    poly_price: float,
    target_size: float = 100.0,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> CompiledArbitrageSet:
    """
    Convert a raw ArbitrageSet dict (from Neo4j) into a CompiledArbitrageSet
    ready for the HotCache. Called by the SemanticAgent after graph compilation.
    """
    now = datetime.now(timezone.utc)
    legs = [
        CachedLeg(
            market_id=arb_graph_dict.get("market_a_id", ""),
            platform="kalshi",
            side="YES",
            action="BUY",
            token_id=None,
            max_price=kalshi_price,
            target_size=target_size,
        ),
        CachedLeg(
            market_id=arb_graph_dict.get("market_b_id", ""),
            platform="polymarket",
            side="NO",
            action="BUY",
            token_id=None,
            max_price=poly_price,
            target_size=target_size,
        ),
    ]
    return CompiledArbitrageSet(
        set_id=arb_graph_dict.get("set_id", ""),
        legs=legs,
        expected_edge_bps=(1.0 - kalshi_price - poly_price) * 10_000,
        min_confidence=arb_graph_dict.get("confidence", 0.0),
        compiled_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        source="graph_compiler",
    )
