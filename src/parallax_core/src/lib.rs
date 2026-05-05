/// parallax_core — Python extension module entry point
///
/// This file binds all Rust components into a single importable Python module.
/// `import parallax_core` from Python gives access to:
///   - parallax_core.Orderbook
///   - parallax_core.ArbitrageResult
///   - parallax_core.compute_arbitrage_edge(...)
///   - parallax_core.scan_depth_for_edge(...)
use pyo3::prelude::*;

pub mod orderbook;
pub mod solver;
pub mod network;
pub mod scanner;

use std::sync::Arc;
use tokio::sync::Mutex;
use orderbook::{Orderbook, OrderbookManager};
use solver::{ArbitrageResult, compute_arbitrage_edge, scan_depth_for_edge};

#[pyclass]
pub struct HotPathEngine {
    manager: Arc<OrderbookManager>,
    scanner: Arc<Mutex<scanner::RustStreamScanner>>,
}

impl Default for HotPathEngine {
    fn default() -> Self {
        Self::new()
    }
}

#[pymethods]
impl HotPathEngine {
    #[new]
    pub fn new() -> Self {
        let manager = Arc::new(OrderbookManager::new());
        let scanner = Arc::new(Mutex::new(scanner::RustStreamScanner::new(manager.clone())));
        Self { manager, scanner }
    }

    pub fn start(&self, _py: Python<'_>) {
        use prometheus::Counter;
        
        let manager = self.manager.clone();
        let scanner = self.scanner.clone();
        
        println!("🚀 HotPathEngine started (Rust-native loop)");
        
        // Initialize metrics
        let tick_counter = Counter::new("parallax_ticks_total", "Total number of scan ticks executed").unwrap();
        
        tokio::spawn(async move {
            // [Opp 4] CPU Pinning
            if let Some(core) = core_affinity::get_core_ids().unwrap_or_default().first() {
                core_affinity::set_for_current(*core);
                println!("📍 Hot path loop pinned to CPU {:?}", core.id);
            }

            loop {
                // [Opp 16] Optimized iteration: Avoid cloning keys into a Vec.
                // We acquire the scanner lock once per cycle for stability.
                {
                    let scanner_guard = scanner.blocking_lock();
                    for entry in manager.books.iter() {
                        let market_id = entry.key();
                        scanner_guard.scan_tick(market_id);
                    }
                }
                
                tick_counter.inc();
                tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            }
        });
    }
}


#[pymodule]
fn parallax_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Orderbook>()?;
    m.add_class::<ArbitrageResult>()?;
    m.add_class::<HotPathEngine>()?;
    m.add_function(wrap_pyfunction!(compute_arbitrage_edge, m)?)?;
    m.add_function(wrap_pyfunction!(scan_depth_for_edge, m)?)?;
    m.add("__version__", "0.2.0")?;
    m.add("__doc__", "Parallax HFT Core — deterministic Rust orderbook and solver")?;
    Ok(())
}
