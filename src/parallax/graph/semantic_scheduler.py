# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/graph/semantic_scheduler.py
#
# Async scheduler that periodically triggers the SemanticAgent
# to scan recently ingested markets and discover new arbitrage pairs.
# Designed to run as a background task inside the FastAPI app lifecycle.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from parallax.config import settings

logger = logging.getLogger(__name__)


async def run_semantic_scan_loop(session_maker) -> None:
    """
    Async background loop. On each iteration:
    1. Queries the SQL DB for markets ingested in the last scan window.
    2. Passes them to SemanticAgent.find_matches() for NLP processing.
    3. Compiles confirmed COMPLEMENT pairs into ArbitrageSet graph nodes.
    4. Broadcasts a telemetry event with the count of new pairs found.
    """
    from parallax.graph.semantic_agent import SemanticAgent
    from parallax.graph.neo4j_repository import Neo4jGraphRepository

    interval = settings.semantic_agent_scan_interval_seconds
    agent = SemanticAgent(model_name=settings.semantic_agent_model)
    graph_repo = Neo4jGraphRepository()

    logger.info(f"🧠 Semantic scan loop started (interval={interval}s)")

    while True:
        try:
            await asyncio.sleep(interval)
            logger.info("🔍 Semantic Agent: starting market scan...")

            markets = await asyncio.to_thread(_fetch_recent_markets, session_maker, interval)
            if not markets:
                logger.info("  No new markets to scan.")
                continue

            logger.info(f"  Scanning {len(markets)} markets for semantic matches...")
            matches = await agent.find_matches(
                markets,
                graph_repo=graph_repo,
                min_similarity=settings.semantic_agent_min_similarity,
            )

            if matches:
                sets = await agent.compile_arbitrage_sets(
                    matches,
                    graph_repo=graph_repo,
                )
                logger.info(f"  ✅ {len(matches)} matches found, {len(sets)} ArbitrageSets compiled.")

                # ── Populate HotCache (L1 + L2 + L3) ─────────────────────────
                # This is the critical step: compiled sets are pushed into the
                # fast cache so the Rust pre-filter can find them on the next tick
                # without any DB round-trip.
                from parallax.cache.hot_cache import HotCache, compile_from_graph
                from parallax.cache.aerospike_adapter import AerospikeAdapter
                cache = HotCache.instance()
                aerospike = AerospikeAdapter()
                for arb_dict in sets:
                    compiled = compile_from_graph(
                        arb_dict,
                        kalshi_price=0.49,   # placeholder until live book available
                        poly_price=0.49,
                        target_size=100.0,
                    )
                    cache.put(compiled)                     # L1 + L2
                    aerospike.write(compiled.set_id, {      # L3 (no-op if offline)
                        "set_id": compiled.set_id,
                        "edge_bps": compiled.expected_edge_bps,
                        "market_ids": compiled.market_ids,
                        "expires_at": compiled.expires_at.isoformat(),
                    })
                logger.info(f"  💾 HotCache stats: {cache.stats()}")

                # Broadcast to War Room
                from parallax.ops.telemetry import broker
                asyncio.create_task(broker.broadcast("semantic_scan_complete", {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "markets_scanned": len(markets),
                    "matches_found": len(matches),
                    "arb_sets_compiled": len(sets),
                    "cache_stats": cache.stats(),
                }))
            else:
                logger.info("  No new matches found.")

        except asyncio.CancelledError:
            logger.info("Semantic scan loop stopped.")
            break
        except Exception as exc:
            logger.error(f"Semantic Agent scan error: {exc}", exc_info=True)


def _fetch_recent_markets(session_maker, lookback_seconds: int) -> list:
    """
    Queries the SQL database for markets updated within the last `lookback_seconds`.
    Returns a list of MarketRecord objects for the semantic agent.
    """
    from parallax.graph.semantic_agent import MarketRecord
    from parallax.db.models import RawMarket
    from datetime import timedelta

    with session_maker() as session:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
        try:
            rows = (
                session.query(RawMarket)
                .filter(RawMarket.created_at >= cutoff)
                .limit(500)
                .all()
            )
        except Exception as exc:
            logger.warning(f"Could not query markets for semantic scan: {exc}")
            return []

    records = []
    for row in rows:
        records.append(MarketRecord(
            market_id=str(row.id),
            platform=getattr(row, "platform", "unknown"),
            question=getattr(row, "question", "") or "",
            description=getattr(row, "description", "") or "",
            end_date=str(row.end_date) if getattr(row, "end_date", None) else None,
        ))
    return records
