"""
Parallax Core — Benchmark & Verification Script

Compares pure-Python orderbook operations vs the Rust-compiled parallax_core module.
Run with:  uv run python tests/scripts/benchmark_rust.py
"""
import time
import sys

# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Verify the module imports and basic API
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 65)
print("  PARALLAX CORE — Rust Extension Verification")
print("=" * 65)

try:
    import parallax_core
    print(f"\n✅  Module loaded:  parallax_core v{parallax_core.__version__}")
except ImportError as e:
    print(f"\n❌  Failed to import parallax_core: {e}")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Section 2: Orderbook correctness tests
# ─────────────────────────────────────────────────────────────────────────────
print("\n[1] Orderbook correctness ...", end=" ")

ob = parallax_core.Orderbook("TRUMP-2024-YES", "kalshi")
ob.update_ask(0.52, 1000.0)
ob.update_ask(0.53, 500.0)
ob.update_bid(0.49, 800.0)
ob.update_bid(0.50, 200.0)

best_ask = ob.best_ask()
best_bid = ob.best_bid()
spread   = ob.spread()

assert best_ask is not None and abs(best_ask[0] - 0.52) < 1e-6, f"Best ask wrong: {best_ask}"
assert best_bid is not None and abs(best_bid[0] - 0.50) < 1e-6, f"Best bid wrong: {best_bid}"
assert spread is not None and abs(spread - 0.02) < 1e-6, f"Spread wrong: {spread}"
assert ob.depth() == (2, 2), f"Depth wrong: {ob.depth()}"

# Remove a level (size=0)
ob.update_ask(0.52, 0.0)
assert ob.depth() == (2, 1), "Level removal failed"

print(f"PASS  ({ob})")

# ─────────────────────────────────────────────────────────────────────────────
# Section 3: Arbitrage solver correctness
# ─────────────────────────────────────────────────────────────────────────────
print("\n[2] Arbitrage solver correctness ...", end=" ")

# YES @ 0.46 on Kalshi, NO @ 0.46 on Polymarket → sum = 0.92 → 800bps raw edge
result = parallax_core.compute_arbitrage_edge(
    a_ask=0.46,
    b_ask=0.46,
    a_ask_size=500.0,
    b_ask_size=500.0,
    friction_bps=30.0,    # 0.30% total friction
    capital_limit=1000.0,
)
assert result.is_executable, "Expected executable arbitrage"
assert abs(result.raw_edge_bps - 800.0) < 0.01, f"Raw edge wrong: {result.raw_edge_bps}"
assert abs(result.net_edge_bps - 770.0) < 0.01, f"Net edge wrong: {result.net_edge_bps}"
assert result.max_executable_size > 0, "Expected positive size"
print(f"PASS  ({result})")

# No-edge case: sum ≥ 1.0
no_edge = parallax_core.compute_arbitrage_edge(0.55, 0.50, 500.0, 500.0, 30.0, 1000.0)
assert not no_edge.is_executable, "Expected no executable arbitrage (sum = 1.05)"
print("[3] No-edge case .............. PASS")

# Depth scanning
print("[4] Depth scan ................", end=" ")
a_asks = [(0.52, 200.0), (0.49, 100.0)]   # level 2 is cheaper
b_asks = [(0.48, 150.0), (0.46, 80.0)]
best = parallax_core.scan_depth_for_edge(a_asks, b_asks, friction_bps=20.0, capital_limit=500.0)
assert best.is_executable, f"Expected executable depth scan: {best}"
print(f"PASS  (best PnL=${best.estimated_pnl:.4f})")

# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Latency benchmark — Rust vs Python
# ─────────────────────────────────────────────────────────────────────────────
N = 1_000_000
print(f"\n[5] Latency benchmark ({N:,} iterations)")
print("    Comparing: parallax_core.Orderbook  vs  Python dict-based orderbook\n")

# ── Rust Orderbook Benchmark ──────────────────────────────────────────────────
rust_ob = parallax_core.Orderbook("BENCH", "test")
t0 = time.perf_counter()
for i in range(N):
    price = 0.40 + (i % 20) * 0.01   # 20 rotating price levels
    rust_ob.update_ask(price, float(i % 100 + 1))
rust_best = rust_ob.best_ask()
t_rust = time.perf_counter() - t0

# ── Python dict Orderbook Benchmark ───────────────────────────────────────────
py_book: dict[int, float] = {}
SCALE = 10_000

t0 = time.perf_counter()
for i in range(N):
    price = 0.40 + (i % 20) * 0.01
    key = int(price * SCALE)
    size = float(i % 100 + 1)
    if size <= 0:
        py_book.pop(key, None)
    else:
        py_book[key] = size
py_best = min(py_book.items())[1] if py_book else None
t_python = time.perf_counter() - t0

speedup = t_python / t_rust

print(f"    🦀  Rust   : {t_rust * 1000:.2f} ms  ({t_rust / N * 1e9:.1f} ns/op)")
print(f"    🐍  Python : {t_python * 1000:.2f} ms  ({t_python / N * 1e9:.1f} ns/op)")
print(f"    📈  Speedup: {speedup:.1f}×")

print("\n" + "=" * 65)
print("  All checks PASSED ✅" if speedup >= 1.0 else "  ⚠️  Rust not faster than Python (unexpected)")
print("=" * 65 + "\n")
