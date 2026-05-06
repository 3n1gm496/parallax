/// parallax_core — Deterministic Orderbook implementation
///
/// Design goals (2026 HFT standard):
/// - Zero heap allocation per tick update (all ops work on pre-allocated BTreeMaps)
/// - Lock-free reads from Python (GIL released during pure computation)
/// - O(log N) insert/delete, O(1) best-bid / best-ask lookups
use std::collections::BTreeMap;
use pyo3::prelude::*;

/// Price level representation.
/// Using fixed-point integer (×1,000,000) internally to avoid floating-point drift.
/// 0.51 → stored as 510,000 (6 decimal places of precision)
const SCALE: f64 = 1_000_000.0;

#[inline(always)]
fn to_fixed(price: f64) -> i128 {
    (price * SCALE).round() as i128
}

#[inline(always)]
fn from_fixed(p: i128) -> f64 {
    p as f64 / SCALE
}

/// A single side of the orderbook (bids or asks).
/// Keys are price in fixed-point integer (higher = better for bids, lower = better for asks).
/// Values are the available size at that price level.
#[derive(Debug, Default, Clone)]
struct BookSide {
    levels: BTreeMap<i128, f64>,
}

impl BookSide {
    fn update(&mut self, price: f64, size: f64) {
        let key = to_fixed(price);
        if size <= 0.0 {
            self.levels.remove(&key);
        } else {
            self.levels.insert(key, size);
        }
    }

    /// Best bid → highest price key
    fn best_bid(&self) -> Option<(f64, f64)> {
        self.levels.iter().next_back().map(|(&k, &v)| (from_fixed(k), v))
    }

    /// Best ask → lowest price key
    fn best_ask(&self) -> Option<(f64, f64)> {
        self.levels.iter().next().map(|(&k, &v)| (from_fixed(k), v))
    }

    /// Internal raw access for Rust-to-Rust solver
    pub fn levels_raw(&self) -> &BTreeMap<i128, f64> {
        &self.levels
    }

    /// Zero-allocation iterator for Rust-native solver
    pub fn iter_levels(&self) -> impl Iterator<Item = (f64, f64)> + Clone + '_ {
        self.levels.iter().map(|(&k, &v)| (from_fixed(k), v))
    }

    /// Format for solver: Vec<(price, size)>
    pub fn as_vec(&self) -> Vec<(f64, f64)> {
        self.iter_levels().collect()
    }

    /// Compute available quantity up to a given price limit (for taker/aggressor sizing)
    fn available_qty_at_or_better(&self, limit: f64, is_bid: bool) -> f64 {
        let limit_key = to_fixed(limit);
        let mut total = 0.0f64;
        for (&k, &v) in &self.levels {
            if (is_bid && k >= limit_key) || (!is_bid && k <= limit_key) {
                total += v;
            }
        }
        total
    }
}

/// Parallax Orderbook — exposes full depth-of-book to Python via PyO3.
/// Thread-safe via Python GIL ownership.
#[pyclass(name = "Orderbook")]
#[derive(Clone)]
pub struct Orderbook {
    bids: BookSide,
    asks: BookSide,
    market_id: String,
    venue: String,
    last_update_ns: u64, // Unix nanoseconds
}

#[pymethods]
impl Orderbook {
    #[new]
    pub fn new(market_id: String, venue: String) -> Self {
        Orderbook {
            bids: BookSide::default(),
            asks: BookSide::default(),
            market_id,
            venue,
            last_update_ns: 0,
        }
    }

    /// Update a bid level. size=0.0 removes the level.
    pub fn update_bid(&mut self, price: f64, size: f64) {
        self.bids.update(price, size);
    }

    /// [PHASE 3] Batch update bids from a list of (price, size) tuples.
    pub fn batch_update_bids(&mut self, levels: Vec<(f64, f64)>) {
        for (price, size) in levels {
            self.bids.update(price, size);
        }
    }

    /// Update an ask level. size=0.0 removes the level.
    pub fn update_ask(&mut self, price: f64, size: f64) {
        self.asks.update(price, size);
    }

    /// [PHASE 3] Batch update asks from a list of (price, size) tuples.
    pub fn batch_update_asks(&mut self, levels: Vec<(f64, f64)>) {
        for (price, size) in levels {
            self.asks.update(price, size);
        }
    }

    /// Set the last update timestamp (nanoseconds since UNIX epoch).
    pub fn set_last_update_ns(&mut self, ts_ns: u64) {
        self.last_update_ns = ts_ns;
    }

    /// Returns (best_bid_price, best_bid_size) or None
    pub fn best_bid(&self, py: Python) -> PyObject {
        match self.bids.best_bid() {
            Some((p, s)) => (p, s).into_pyobject(py).unwrap().into_any().unbind(),
            None => py.None(),
        }
    }

    /// Returns (best_ask_price, best_ask_size) or None
    pub fn best_ask(&self, py: Python) -> PyObject {
        match self.asks.best_ask() {
            Some((p, s)) => (p, s).into_pyobject(py).unwrap().into_any().unbind(),
            None => py.None(),
        }
    }

    /// Returns the mid-price or None if the book is empty on either side.
    pub fn mid_price(&self, py: Python) -> PyObject {
        match (self.bids.best_bid(), self.asks.best_ask()) {
            (Some((b, _)), Some((a, _))) => ((b + a) / 2.0).into_pyobject(py).unwrap().into_any().unbind(),
            _ => py.None(),
        }
    }

    /// Returns the current bid-ask spread or None.
    pub fn spread(&self, py: Python) -> PyObject {
        match (self.bids.best_bid(), self.asks.best_ask()) {
            (Some((b, _)), Some((a, _))) => (a - b).into_pyobject(py).unwrap().into_any().unbind(),
            _ => py.None(),
        }
    }

    /// Available quantity to buy at or below a given price limit.
    pub fn available_ask_qty(&self, limit: f64) -> f64 {
        self.asks.available_qty_at_or_better(limit, false)
    }

    /// Available quantity to sell at or above a given price limit.
    pub fn available_bid_qty(&self, limit: f64) -> f64 {
        self.bids.available_qty_at_or_better(limit, true)
    }

    /// Number of price levels on each side.
    pub fn depth(&self) -> (usize, usize) {
        (self.bids.levels.len(), self.asks.levels.len())
    }

    pub fn market_id(&self) -> &str {
        &self.market_id
    }

    pub fn venue(&self) -> &str {
        &self.venue
    }

    pub fn last_update_ns(&self) -> u64 {
        self.last_update_ns
    }

    pub fn __repr__(&self) -> String {
        let bid = self.bids.best_bid().map(|(p, s)| format!("{p:.4}@{s:.2}")).unwrap_or("—".into());
        let ask = self.asks.best_ask().map(|(p, s)| format!("{p:.4}@{s:.2}")).unwrap_or("—".into());
        format!("Orderbook({} {}) bid={} ask={}", self.venue, self.market_id, bid, ask)
    }

    /// [PHASE 3] Internal clone for manager
    pub fn clone_internal(&self) -> Self {
        self.clone()
    }
}

// Rust-only methods not exposed to Python
impl Orderbook {
    pub fn bids_raw(&self) -> &BTreeMap<i128, f64> {
        self.bids.levels_raw()
    }

    pub fn asks_raw(&self) -> &BTreeMap<i128, f64> {
        self.asks.levels_raw()
    }

    pub fn bids_as_vec(&self) -> Vec<(f64, f64)> {
        self.bids.as_vec()
    }

    pub fn asks_as_vec(&self) -> Vec<(f64, f64)> {
        self.asks.as_vec()
    }

    pub fn iter_bids(&self) -> impl Iterator<Item = (f64, f64)> + Clone + '_ {
        self.bids.iter_levels()
    }

    pub fn iter_asks(&self) -> impl Iterator<Item = (f64, f64)> + Clone + '_ {
        self.asks.iter_levels()
    }
}


use dashmap::DashMap;

/// Manages multiple orderbooks across different venues.
/// This is the central hub for the Rust-native hot path.
#[pyclass]
pub struct OrderbookManager {
    pub books: DashMap<String, Orderbook>,
}

#[pymethods]
impl OrderbookManager {
    #[new]
    pub fn new() -> Self {
        Self {
            books: DashMap::new(),
        }
    }

    /// [PHASE 3] Batch update bids for a specific market.
    pub fn batch_update_bids(&self, market_id: String, venue: String, levels: Vec<(f64, f64)>) {
        let mut book = self.books.entry(market_id.clone()).or_insert_with(|| {
            Orderbook::new(market_id, venue)
        });
        book.batch_update_bids(levels);
    }

    /// [PHASE 3] Batch update asks for a specific market.
    pub fn batch_update_asks(&self, market_id: String, venue: String, levels: Vec<(f64, f64)>) {
        let mut book = self.books.entry(market_id.clone()).or_insert_with(|| {
            Orderbook::new(market_id, venue)
        });
        book.batch_update_asks(levels);
    }

    /// Returns a COPY of the orderbook for Python. 
    /// (DashMap guards are tricky to expose directly as mutable refs).
    pub fn get_book(&self, market_id: &str) -> Option<Orderbook> {
        self.books.get(market_id).map(|b| {
            // We need a way to clone Orderbook. Let's add Clone to Orderbook.
            // For now, we'll manually rebuild it or just return None if not easy.
            // Let's add #[derive(Clone)] to Orderbook.
            b.value().clone_internal()
        })
    }

    pub fn update_bid(&self, market_id: &str, venue: &str, price: f64, size: f64) {
        if let Some(mut book) = self.books.get_mut(market_id) {
            book.update_bid(price, size);
            return;
        }
        
        let mut book = self.books.entry(market_id.to_string()).or_insert_with(|| {
            Orderbook::new(market_id.to_string(), venue.to_string())
        });
        book.update_bid(price, size);
    }

    pub fn update_ask(&self, market_id: &str, venue: &str, price: f64, size: f64) {
        if let Some(mut book) = self.books.get_mut(market_id) {
            book.update_ask(price, size);
            return;
        }

        let mut book = self.books.entry(market_id.to_string()).or_insert_with(|| {
            Orderbook::new(market_id.to_string(), venue.to_string())
        });
        book.update_ask(price, size);
    }
}

