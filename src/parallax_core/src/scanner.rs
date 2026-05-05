use std::sync::Arc;
use crate::orderbook::OrderbookManager;

pub struct RustStreamScanner {
    manager: Arc<OrderbookManager>,
    // cluster_id -> (list of market_ids, confidence_score)
    clusters: std::collections::HashMap<String, (Vec<String>, f64)>,
}

impl RustStreamScanner {
    pub fn new(manager: Arc<OrderbookManager>) -> Self {
        Self {
            manager,
            clusters: std::collections::HashMap::new(),
        }
    }

    pub fn update_clusters(&mut self, new_clusters: std::collections::HashMap<String, (Vec<String>, f64)>) {
        self.clusters = new_clusters;
    }

    pub fn scan_tick(&self, market_id: &str) {
        // 1. Find clusters involving this market
        // TODO: Optimization - cache this mapping
        let mut affected_clusters: Vec<(&String, f64)> = self.clusters.iter()
            .filter(|(_, (markets, _))| markets.iter().any(|m| m == market_id))
            .map(|(id, (_, conf))| (id, *conf))
            .collect();

        if affected_clusters.is_empty() {
            return;
        }

        // Sort clusters by confidence descending
        affected_clusters.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        for (cluster_id, _) in affected_clusters {
            let (market_ids, _) = &self.clusters[cluster_id];
            
            let eval_limit = std::cmp::min(20, market_ids.len());
            let top_markets = &market_ids[0..eval_limit];
            
            for i in 0..top_markets.len() {
                for j in i+1..top_markets.len() {
                    let m1_id = &top_markets[i];
                    let m2_id = &top_markets[j];

                    if let (Some(b1), Some(b2)) = (self.manager.books.get(m1_id), self.manager.books.get(m2_id)) {
                        let _result = crate::solver::scan_depth_internal(
                            b1.iter_asks(),
                            b2.iter_asks(),
                            30.0, // friction
                            1000.0, // capital
                        );

                        // [BUG FIX] Removed blocking println! from hot path.
                        // In production, this should trigger an event via a lock-free ring buffer.
                        // if result.is_executable {
                        //    ...
                        // }
                    }
                }
            }
        }
    }
}

