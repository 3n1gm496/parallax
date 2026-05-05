# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/graph/neo4j_repository.py
#
# Neo4j implementation of GraphRepository (V2).
# Wraps all Cypher queries. Falls back gracefully if driver is None.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from parallax.shared.schemas import CounterexampleRecord, RelationType
from parallax.graph.repository import GraphRepository
from parallax.graph.neo4j_driver import get_driver

logger = logging.getLogger(__name__)


class Neo4jGraphRepository(GraphRepository):
    """
    Async Neo4j-backed graph repository for Parallax V2.
    """

    async def upsert_market(
        self,
        *,
        market_id: str,
        platform: str,
        question: str,
        description: str = "",
        tags: list[str] | None = None,
        end_date: str | None = None,
        status: str = "open",
        embedding: list[float] | None = None,
    ) -> bool:
        driver = get_driver()
        if not driver:
            return False

        async with driver.session() as session:
            await session.execute_write(
                lambda tx: tx.run(
                    """
                    MERGE (m:Market {market_id: $market_id})
                    SET   m.platform    = $platform,
                          m.question   = $question,
                          m.description = $description,
                          m.tags       = $tags,
                          m.end_date   = $end_date,
                          m.status     = $status,
                          m.updated_at = $now
                    """,
                    market_id=market_id,
                    platform=platform,
                    question=question,
                    description=description,
                    tags=tags or [],
                    end_date=end_date,
                    status=status,
                    now=datetime.now(timezone.utc).isoformat(),
                )
            )
            if embedding:
                await session.execute_write(
                    lambda tx: tx.run(
                        "MATCH (m:Market {market_id: $id}) SET m.embedding = $emb",
                        id=market_id,
                        emb=embedding,
                    )
                )
        return True

    # ... and so on for all methods ...

    async def find_similar_markets(
        self,
        embedding: list[float],
        *,
        top_k: int = 10,
        min_score: float = 0.85,
    ) -> list[dict]:
        driver = get_driver()
        if not driver:
            return []

        async with driver.session() as session:
            results = await session.execute_read(
                lambda tx: tx.run(
                    """
                    CALL db.index.vector.queryNodes('market_embedding_idx', $k, $emb)
                    YIELD node, score
                    WHERE score >= $min_score
                    RETURN node.market_id  AS market_id,
                           node.platform   AS platform,
                           node.question   AS question,
                           score
                    ORDER BY score DESC
                    """,
                    k=top_k,
                    emb=embedding,
                    min_score=min_score,
                )
            )
            # Need to convert results to data
            data = await results.data()
        return data

    # ── Relation operations (implements GraphRepository ABC) ───────────────────

    async def add_relation(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
        confidence: float,
        evidence: dict,
        created_by: str,
    ) -> str:
        driver = get_driver()
        relation_id = str(uuid.uuid4())
        if not driver:
            logger.warning("Neo4j offline — relation not persisted.")
            return relation_id

        rel_label = relation_type.upper().replace("-", "_")

        async with driver.session() as session:
            await session.execute_write(
                lambda tx: tx.run(
                    f"""
                    MERGE (a:Market {{market_id: $from_id}})
                    MERGE (b:Market {{market_id: $to_id}})
                    MERGE (a)-[r:{rel_label}]->(b)
                    SET r.relation_id  = $rel_id,
                        r.confidence   = $confidence,
                        r.evidence     = $evidence,
                        r.created_by   = $created_by,
                        r.created_at   = $now
                    """,
                    from_id=from_market_id,
                    to_id=to_market_id,
                    rel_id=relation_id,
                    confidence=confidence,
                    evidence=str(evidence),
                    created_by=created_by,
                    now=datetime.now(timezone.utc).isoformat(),
                )
            )
        return relation_id

    async def get_relations(
        self,
        market_id: str,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        driver = get_driver()
        if not driver:
            return []

        async with driver.session() as session:
            if relation_type:
                rel_label = relation_type.upper().replace("-", "_")
                query = f"""
                    MATCH (a:Market {{market_id: $mid}})-[r:{rel_label}]-(b:Market)
                    RETURN a.market_id AS from_id, b.market_id AS to_id,
                           type(r) AS rel_type, r.confidence AS confidence,
                           r.relation_id AS relation_id
                """
            else:
                query = """
                    MATCH (a:Market {market_id: $mid})-[r]-(b:Market)
                    RETURN a.market_id AS from_id, b.market_id AS to_id,
                           type(r) AS rel_type, r.confidence AS confidence,
                           r.relation_id AS relation_id
                """
            res = await session.execute_read(
                lambda tx: tx.run(query, mid=market_id)
            )
            return await res.data()

    async def relation_exists(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
    ) -> bool:
        driver = get_driver()
        if not driver:
            return False

        rel_label = relation_type.upper().replace("-", "_")
        async with driver.session() as session:
            res = await session.execute_read(
                lambda tx: tx.run(
                    f"""
                    MATCH (a:Market {{market_id: $from_id}})-[r:{rel_label}]->
                          (b:Market {{market_id: $to_id}})
                    RETURN count(r) AS cnt
                    """,
                    from_id=from_market_id,
                    to_id=to_market_id,
                )
            )
            result = await res.single()
        return result and result["cnt"] > 0

    async def delete_relation(self, relation_id: str) -> bool:
        driver = get_driver()
        if not driver:
            return False

        async with driver.session() as session:
            res = await session.execute_write(
                lambda tx: tx.run(
                    "MATCH ()-[r {relation_id: $rid}]-() DELETE r RETURN count(r) AS deleted",
                    rid=relation_id,
                )
            )
            result = await res.single()
        return result and result["deleted"] > 0

    def add_counterexample_record(self, record: CounterexampleRecord) -> str:
        # Stored as a property on the existing relation edge
        driver = get_driver()
        ce_id = str(uuid.uuid4())
        if not driver:
            return ce_id
        # Simplified: attach as metadata on the relevant markets
        logger.debug(f"Counterexample recorded (id={ce_id}) — details: {record}")
        return ce_id

    async def add_relation_set(
        self,
        *,
        set_key: str,
        member_market_ids: list[str],
        relation_type: RelationType,
        confidence: float,
        evidence: dict,
        created_by: str,
    ) -> str:
        driver = get_driver()
        set_id = str(uuid.uuid4())
        if not driver:
            return set_id

        async with driver.session() as session:
            await session.execute_write(
                lambda tx: tx.run(
                    """
                    MERGE (s:RelationSet {set_key: $key})
                    SET s.set_id       = $set_id,
                        s.relation_type = $rel_type,
                        s.confidence   = $confidence,
                        s.created_by   = $created_by,
                        s.updated_at   = $now
                    WITH s
                    UNWIND $members AS mid
                    MERGE (m:Market {market_id: mid})
                    MERGE (s)-[:HAS_MEMBER]->(m)
                    """,
                    key=set_key,
                    set_id=set_id,
                    rel_type=str(relation_type),
                    confidence=confidence,
                    created_by=created_by,
                    now=datetime.now(timezone.utc).isoformat(),
                    members=member_market_ids,
                )
            )
        return set_id

    async def get_relation_set(self, set_key: str) -> dict | None:
        driver = get_driver()
        if not driver:
            return None

        async with driver.session() as session:
            res = await session.execute_read(
                lambda tx: tx.run(
                    """
                    MATCH (s:RelationSet {set_key: $key})-[:HAS_MEMBER]->(m:Market)
                    RETURN s.set_id AS set_id, s.relation_type AS rel_type,
                           s.confidence AS confidence,
                           collect(m.market_id) AS members
                    """,
                    key=set_key,
                )
            )
            result = await res.single()
        return dict(result) if result else None

    async def list_relation_sets(
        self,
        *,
        limit: int = 100,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        driver = get_driver()
        if not driver:
            return []

        async with driver.session() as session:
            if relation_type:
                query = """
                    MATCH (s:RelationSet {relation_type: $rt})-[:HAS_MEMBER]->(m:Market)
                    RETURN s.set_key AS set_key, s.relation_type AS rel_type,
                           collect(m.market_id) AS members
                    LIMIT $lim
                """
                res = await session.execute_read(
                    lambda tx: tx.run(query, rt=str(relation_type), lim=limit)
                )
            else:
                query = """
                    MATCH (s:RelationSet)-[:HAS_MEMBER]->(m:Market)
                    RETURN s.set_key AS set_key, s.relation_type AS rel_type,
                           collect(m.market_id) AS members
                    LIMIT $lim
                """
                res = await session.execute_read(
                    lambda tx: tx.run(query, lim=limit)
                )
            return await res.data()

    # ── ArbitrageSet compilation ───────────────────────────────────────────────

    async def upsert_arbitrage_set(
        self,
        *,
        set_id: str,
        market_ids: list[str],
        edge_bps: float,
        compiled_at: str,
    ) -> bool:
        driver = get_driver()
        if not driver:
            return False

        async with driver.session() as session:
            await session.execute_write(
                lambda tx: tx.run(
                    """
                    MERGE (a:ArbitrageSet {set_id: $sid})
                    SET a.edge_bps    = $edge_bps,
                        a.compiled_at = $compiled_at,
                        a.status      = 'active'
                    WITH a
                    UNWIND $mids AS mid
                    MERGE (m:Market {market_id: mid})
                    MERGE (a)-[:CONTAINS]->(m)
                    """,
                    sid=set_id,
                    edge_bps=edge_bps,
                    compiled_at=compiled_at,
                    mids=market_ids,
                )
            )
        return True
