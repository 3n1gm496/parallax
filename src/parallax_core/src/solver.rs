/// parallax_core — Deterministic Arbitrage Solver
///
/// This module contains the pure mathematical computation that determines whether
/// a cross-venue arbitrage opportunity is executable and what the net edge is.
///
/// Design goals:
/// - Zero allocations (all inputs are primitives)
/// - Pure functions — no side effects, no I/O, no locks
/// - Designed to be called millions of times per second from Rust or Python
use pyo3::prelude::*;

/// A single computed arbitrage edge across two venues.
#[pyclass(name = "ArbitrageResult")]
#[derive(Debug, Clone)]
pub struct ArbitrageResult {
    /// True if the opportunity is executable (positive edge after friction)
    #[pyo3(get)]
    pub is_executable: bool,

    /// Raw edge before friction costs (basis points)
    #[pyo3(get)]
    pub raw_edge_bps: f64,

    /// Net edge after friction costs (basis points)
    #[pyo3(get)]
    pub net_edge_bps: f64,

    /// Estimated PnL in dollars for the given notional
    #[pyo3(get)]
    pub estimated_pnl: f64,

    /// The optimal leg A price (taker)
    #[pyo3(get)]
    pub leg_a_price: f64,

    /// The optimal leg B price (taker)
    #[pyo3(get)]
    pub leg_b_price: f64,

    /// Maximum position size limited by available liquidity
    #[pyo3(get)]
    pub max_executable_size: f64,
}

#[pymethods]
impl ArbitrageResult {
    pub fn __repr__(&self) -> String {
        format!(
            "ArbitrageResult(executable={}, net_edge={:.2}bps, pnl=${:.4}, max_size={:.2})",
            self.is_executable, self.net_edge_bps, self.estimated_pnl, self.max_executable_size
        )
    }
}

/// Core arbitrage computation function.
///
/// Strategy: "YES Spread Arbitrage"
/// Buy YES on venue A (at ask price a_ask) + Buy NO on venue B (at ask price b_ask).
/// If a_ask + b_ask < 1.0, a risk-free profit is guaranteed at settlement.
///
/// Args:
///   a_ask:          Best ask price on venue A for the "YES" outcome [0, 1]
///   b_ask:          Best ask price on venue B for the "NO" outcome [0, 1]
///   a_ask_size:     Available size at a_ask
///   b_ask_size:     Available size at b_ask
///   friction_bps:   Total friction estimate (exchange fees + gas + slippage) in basis points
///   capital_limit:  Maximum capital to deploy in dollars
///
/// Returns:
///   ArbitrageResult with all computed metrics.
#[pyfunction]
pub fn compute_arbitrage_edge(
    a_ask: f64,
    b_ask: f64,
    a_ask_size: f64,
    b_ask_size: f64,
    friction_bps: f64,
    capital_limit: f64,
) -> ArbitrageResult {
    // The guaranteed payoff at settlement is always 1.0 (one of YES or NO resolves to 1.0).
    // So raw edge = 1.0 - (cost of buying both sides)
    let total_cost_per_unit = a_ask + b_ask;
    let raw_edge = 1.0 - total_cost_per_unit;

    // Convert to basis points (1 bps = 0.01%)
    let raw_edge_bps = raw_edge * 10_000.0;

    // Subtract friction costs
    let net_edge_bps = raw_edge_bps - friction_bps;
    let net_edge = net_edge_bps / 10_000.0;

    // Maximum executable size: limited by the smaller side of available liquidity and capital
    let max_size_by_liquidity = a_ask_size.min(b_ask_size);
    let max_size_by_capital = if total_cost_per_unit > 0.0 {
        capital_limit / total_cost_per_unit
    } else {
        0.0
    };
    let max_executable_size = max_size_by_liquidity.min(max_size_by_capital);

    // PnL = net edge per unit × size
    let estimated_pnl = net_edge * max_executable_size;

    ArbitrageResult {
        is_executable: net_edge_bps > 0.0 && max_executable_size > 0.0,
        raw_edge_bps,
        net_edge_bps,
        estimated_pnl,
        leg_a_price: a_ask,
        leg_b_price: b_ask,
        max_executable_size,
    }
}

/// Scan a full Orderbook pair for the best executable arbitrage,
/// checking multiple price levels (not just top-of-book).
///
/// Args:
///   a_asks:         Vector of (price, size) from venue A ask side, sorted ascending
///   b_asks:         Vector of (price, size) from venue B ask side, sorted ascending
///   friction_bps:   Total friction in basis points
///   capital_limit:  Maximum capital to deploy
///
/// Returns:
///   The best ArbitrageResult found, or a non-executable result if none found.
#[pyfunction]
pub fn scan_depth_for_edge(
    py: Python<'_>,
    a_asks: Vec<(f64, f64)>,
    b_asks: Vec<(f64, f64)>,
    friction_bps: f64,
    capital_limit: f64,
) -> ArbitrageResult {
    // Release GIL for the duration of the scan
    py.allow_threads(|| {
        scan_depth_internal(
            a_asks.iter().cloned(),
            b_asks.iter().cloned(),
            friction_bps,
            capital_limit,
        )
    })
}

/// Zero-allocation internal solver for Rust-native path
pub fn scan_depth_internal<I1, I2>(
    a_asks: I1,
    b_asks: I2,
    friction_bps: f64,
    capital_limit: f64,
) -> ArbitrageResult 
where 
    I1: Iterator<Item = (f64, f64)> + Clone,
    I2: Iterator<Item = (f64, f64)> + Clone,
{
    let mut best: Option<ArbitrageResult> = None;

    for (a_price, a_size) in a_asks {
        for (b_price, b_size) in b_asks.clone() {
            let result = compute_arbitrage_edge(
                a_price,
                b_price,
                a_size,
                b_size,
                friction_bps,
                capital_limit,
            );
            if result.is_executable {
                if let Some(ref cur_best) = best {
                    if result.estimated_pnl > cur_best.estimated_pnl {
                        best = Some(result);
                    }
                } else {
                    best = Some(result);
                }
            }
        }
    }

    best.unwrap_or(ArbitrageResult {
        is_executable: false,
        raw_edge_bps: 0.0,
        net_edge_bps: 0.0,
        estimated_pnl: 0.0,
        leg_a_price: 0.0,
        leg_b_price: 0.0,
        max_executable_size: 0.0,
    })
}
