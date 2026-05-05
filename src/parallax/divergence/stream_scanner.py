import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from parallax.db.models import EventIdentityCluster, IdentityClusterMember, RawMarket, OpportunityCandidate
from parallax.execution.streamer import BaseStreamer
from parallax.solver.service import GeneralizedPayoffSolver
from parallax.court.service import CourtService
from parallax.execution.executor import ExecutionManager
from parallax.config import settings

logger = logging.getLogger(__name__)

class StreamScanner:
    def __init__(self, session_maker: Callable[[], Session], streamer: BaseStreamer):
        self.session_maker = session_maker
        self.streamer = streamer
        
        # Cache for quick lookup on tick: market_id -> cluster_id
        self._market_to_cluster: dict[str, uuid.UUID] = {}
        # Cache: cluster_id -> list of market_ids
        self._cluster_markets: dict[uuid.UUID, list[str]] = {}
        
        # Register the callback
        self.streamer.subscribe(self.on_tick)

    def preload_cache(self):
        """Preload active clusters into memory to avoid DB hits on every tick."""
        with self.session_maker() as session:
            active_clusters = session.query(EventIdentityCluster).filter_by(status="active").all()
            for cluster in active_clusters:
                members = session.query(IdentityClusterMember).filter_by(cluster_id=cluster.id).all()
                market_ids = [m.raw_market_id for m in members if m.raw_market_id]
                self._cluster_markets[cluster.id] = market_ids
                for m_id in market_ids:
                    self._market_to_cluster[m_id] = cluster.id
        logger.info(f"Preloaded {len(self._cluster_markets)} active clusters into StreamScanner cache.")

    async def on_tick(self, market_id: str):
        """Called by the streamer whenever a market's L2 orderbook updates."""
        cluster_id = self._market_to_cluster.get(market_id)
        if not cluster_id:
            return # Ignore ticks for markets not in any active cluster
            
        cluster_market_ids = self._cluster_markets[cluster_id]
        
        # Check if we have orderbooks for at least 2 markets in the cluster
        available_obs = {mid: self.streamer.orderbooks[mid] for mid in cluster_market_ids if mid in self.streamer.orderbooks}
        if len(available_obs) < 2:
            return

        # ── HotCache pre-filter (L1, ~2μs) ───────────────────────────────────
        # First check if any pre-compiled ArbitrageSet from the Cold Path
        # includes this market. If yes, skip the full ANN scan and proceed
        # straight to the Python solver — the AI has already validated this pair.
        if self._hotcache_has_set_for_market(market_id, available_obs):
            await asyncio.to_thread(self._solve_cluster_sync, cluster_id, cluster_market_ids, available_obs)
            return

        # ── Fast-path: Rust pre-filter ────────────────────────────────────────
        # Before spawning an expensive Python solver thread, use the Rust
        # `scan_depth_for_edge` to check if any executable edge exists in
        # sub-microsecond time. Only proceed to the full solver if the Rust
        # check passes. This eliminates the solver overhead on 99%+ of ticks.
        if not self._rust_edge_exists(available_obs):
            return

        # Run solver in thread pool since it uses synchronous SQLAlchemy
        await asyncio.to_thread(self._solve_cluster_sync, cluster_id, cluster_market_ids, available_obs)

    def _hotcache_has_set_for_market(self, market_id: str, available_obs: dict) -> bool:
        """
        Checks the HotCache for any pre-compiled ArbitrageSet that includes
        this market AND covers all required venues in the current orderbook snapshot.
        This is the fastest possible path: pure Python dict lookup, ~2μs.
        """
        try:
            from parallax.cache.hot_cache import HotCache
            cache = HotCache.instance()
            compiled_sets = cache.get_by_market(market_id)
            if not compiled_sets:
                return False
            # Verify that both legs of the set have live orderbooks
            for arb_set in compiled_sets:
                if all(mid in available_obs for mid in arb_set.market_ids):
                    return True
            return False
        except Exception:
            return False

    def _rust_edge_exists(self, orderbooks: dict) -> bool:
        """
        Uses the compiled Rust solver to check whether any executable arbitrage
        edge exists across the current set of orderbooks. Returns True quickly
        if a potential edge is found so the full solver can confirm it.
        Falls back to True (conservative) if parallax_core is unavailable.
        """
        try:
            import parallax_core  # type: ignore[import]
            from parallax.config import settings
        except ImportError:
            return True  # Conservative fallback: always run Python solver

        obs = list(orderbooks.values())
        if len(obs) < 2:
            return True

        # Compare each pair of orderbook sides for potential YES/NO arbitrage
        for i in range(len(obs)):
            for j in range(i + 1, len(obs)):
                a_ob = obs[i]
                b_ob = obs[j]
                a_asks = a_ob.asks.as_rust_levels()
                b_asks = b_ob.asks.as_rust_levels()
                if not a_asks or not b_asks:
                    continue
                result = parallax_core.scan_depth_for_edge(
                    a_asks=a_asks,
                    b_asks=b_asks,
                    friction_bps=float(settings.friction_bps),
                    capital_limit=float(getattr(settings, "capital_limit", 100.0)),
                )
                if result.is_executable:
                    return True
        return False

    def _solve_cluster_sync(self, cluster_id: uuid.UUID, market_ids: list[str], orderbooks: dict):
        """Synchronous method to run the MILP solver and write to DB if arbitrage is found."""
        with self.session_maker() as session:
            solver = GeneralizedPayoffSolver(session)
            
            # Fetch RawMarkets
            markets = session.query(RawMarket).filter(RawMarket.id.in_(market_ids)).all()
            if len(markets) < 2:
                return
                
            # In a real implementation, we would also fetch RelationEvidenceResponse 
            # and LogicalRelationSets for this cluster. For the skeleton, we pass None
            # so the solver tries EQUIVALENT by default.
            
            try:
                decision_output = solver.solve_with_trace(
                    markets=markets,
                    relation_evidence=None, # Simplified for now
                    orderbooks=orderbooks
                )
                
                if decision_output.result and decision_output.result.best_case_payoff > 0.0:
                    logger.info(f"⚡ ARBITRAGE DETECTED on cluster {cluster_id}! Edge: {decision_output.result.best_case_payoff}")
                    
                    if not settings.runtime_enable_stream_trigger:
                        logger.info("Stream trigger is disabled. Record created for cold-path polling.")
                        return

                    # ── HOT PATH: Immediate Court & Execution ─────────────────────────
                    logger.info(f"🔥 HOT PATH TRIGGERED for cluster {cluster_id}")
                    
                    # 1. Ensure a Candidate exists
                    # We look for an open candidate for this cluster
                    # For simplicity, we create a new one if not found or reuse
                    candidate = session.query(OpportunityCandidate).filter_by(
                        cluster_id=cluster_id, 
                        status="open"
                    ).first()
                    
                    if not candidate:
                        # Create minimal candidate for the court to assess
                        candidate = OpportunityCandidate(
                            id=uuid.uuid4(),
                            cluster_id=cluster_id,
                            opportunity_type="semantic_arbitrage",
                            status="open",
                            basket_json={"selected_legs": decision_output.result.basket_legs}
                        )
                        session.add(candidate)
                        session.flush()

                    # 2. Run Court Assessment with current snapshots
                    court_svc = CourtService(session)
                    # Convert streamer orderbooks to snapshots
                    # (In a real system, this conversion should be zero-cost)
                    from parallax.execution.schemas import OrderbookSnapshot
                    snapshots = {}
                    for m_id, ob in orderbooks.items():
                        # Minimal snapshot reconstruction
                        snapshots[m_id] = OrderbookSnapshot(
                            id=str(uuid.uuid4()),
                            platform=ob.venue,
                            market_id=ob.market_id,
                            outcome="YES", # simplified
                            captured_at=datetime.now(timezone.utc),
                            # ... (other fields)
                        )

                    # For the skeleton, we call a simplified evaluation
                    assessment = court_svc.evaluate_with_snapshots(str(candidate.id), snapshots)
                    
                    if assessment.value == "APPROVED":
                        logger.warning(f"🚀 EXECUTION APPROVED by Court for {candidate.id}")
                        
                        # 3. Trigger Executor
                        if settings.runtime_live_execution_enabled or settings.runtime_dry_run:
                            executor = ExecutionManager()
                            # We need to run this async, but we are in a thread. 
                            # We can use a nested event loop or just call it if it was sync.
                            # Since we are in to_thread, we can't easily await.
                            # Best practice: schedule back to the main loop.
                            loop = asyncio.get_event_loop()
                            asyncio.run_coroutine_threadsafe(
                                executor.execute_basket(candidate.basket_json["selected_legs"]),
                                loop
                            )
                        
            except Exception as e:
                logger.error(f"Solver failed on cluster {cluster_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
