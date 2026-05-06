use std::sync::Arc;
use crate::orderbook::OrderbookManager;

pub struct RustStreamScanner {
    manager: Arc<OrderbookManager>,
    // cluster_id -> (list of market_ids, confidence_score)
    clusters: std::collections::HashMap<String, (Vec<String>, f64)>,
    // [Audit Fix] O(1) lookup cache: market_id -> list of cluster_ids
    market_to_clusters: std::collections::HashMap<String, Vec<String>>,
}

impl RustStreamScanner {
    pub fn new(manager: Arc<OrderbookManager>) -> Self {
        Self {
            manager,
            clusters: std::collections::HashMap::new(),
            market_to_clusters: std::collections::HashMap::new(),
        }
    }

    pub fn update_clusters(&mut self, new_clusters: std::collections::HashMap<String, (Vec<String>, f64)>) {
        let mut mapping = std::collections::HashMap::new();
        for (cluster_id, (markets, _)) in new_clusters.iter() {
            for m in markets {
                mapping.entry(m.clone()).or_insert_with(Vec::new).push(cluster_id.clone());
            }
        }
        self.clusters = new_clusters;
        self.market_to_clusters = mapping;
    }

    pub fn scan_tick(&self, market_id: &str, friction_bps: f64, capital_limit: f64) {
        // [Audit Fix] Using O(1) cache instead of O(N) iteration
        let cluster_ids = match self.market_to_clusters.get(market_id) {
            Some(ids) => ids,
            None => return,
        };

        for cluster_id in cluster_ids {
            let (market_ids, _) = &self.clusters[cluster_id];
            
            let eval_limit = std::cmp::min(20, market_ids.len());
            let top_markets = &market_ids[0..eval_limit];
            
            for i in 0..top_markets.len() {
                for j in i+1..top_markets.len() {
                    let m1_id = &top_markets[i];
                    let m2_id = &top_markets[j];

                    if let (Some(b1), Some(b2)) = (self.manager.books.get(m1_id), self.manager.books.get(m2_id)) {
                        // [Audit Fix] Pass dynamic parameters from Python
                        let _result = crate::solver::scan_depth_internal(
                            b1.iter_asks(),
                            b2.iter_asks(),
                            friction_bps,
                            capital_limit,
                        );
                    }
                }
            }
        }
    }
}

