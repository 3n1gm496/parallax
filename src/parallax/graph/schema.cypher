# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/graph/schema.cypher
#
# Neo4j Knowledge Graph Schema for Parallax HFT V2
# Run once to initialize indexes and constraints.
#
# Nodes:
#   (:Market)          — a tradeable prediction market contract
#   (:Entity)          — a real-world entity (person, event, team, stat)
#   (:ArbitrageSet)    — a validated executable arbitrage basket
#
# Edges:
#   (:Market)-[:REFERENCES]->(:Entity)    — market resolves based on this entity
#   (:Market)-[:EQUIVALENT_TO {confidence, evidence}]->(:Market)   — semantic match
#   (:Market)-[:COMPLEMENT_OF {confidence}]->(:Market)   — YES/NO complement
#   (:Market)-[:CORRELATED_WITH {pearson_r}]->(:Market)  — statistical correlation
#   (:ArbitrageSet)-[:CONTAINS {role}]->(:Market)        — basket membership
# ─────────────────────────────────────────────────────────────────────────────

// ── Constraints (uniqueness + existence) ─────────────────────────────────────
CREATE CONSTRAINT market_id_unique IF NOT EXISTS
  FOR (m:Market) REQUIRE m.market_id IS UNIQUE;

CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
  FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE;

CREATE CONSTRAINT arb_set_id_unique IF NOT EXISTS
  FOR (a:ArbitrageSet) REQUIRE a.set_id IS UNIQUE;

// ── Full-text index for hybrid search (exact name + venue search) ─────────────
CREATE FULLTEXT INDEX market_fulltext IF NOT EXISTS
  FOR (m:Market)
  ON EACH [m.question, m.description, m.tags];

// ── Vector index for semantic embedding similarity (ANN, HNSW) ────────────────
// Dimension = 384 (all-MiniLM-L6-v2 / paraphrase-multilingual models)
CREATE VECTOR INDEX market_embedding_idx IF NOT EXISTS
  FOR (m:Market)
  ON m.embedding
  OPTIONS {
    indexConfig: {
      `vector.dimensions`: 384,
      `vector.similarity_function`: 'cosine'
    }
  };

// ── Regular indexes ───────────────────────────────────────────────────────────
CREATE INDEX market_platform_idx IF NOT EXISTS FOR (m:Market) ON (m.platform);
CREATE INDEX market_status_idx   IF NOT EXISTS FOR (m:Market) ON (m.status);
CREATE INDEX entity_type_idx     IF NOT EXISTS FOR (e:Entity) ON (e.entity_type);
