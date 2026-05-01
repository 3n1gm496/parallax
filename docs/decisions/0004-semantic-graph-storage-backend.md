# ADR-0004: Semantic Graph Storage Backend

Status: Accepted
Date: 2026-04-29

## Context

PARALLAX's Semantic Market Graph stores:
- Canonical event nodes (RealWorldEvent)
- Market nodes linked to canonical events
- Typed relations between markets: equivalent, duplicate, subset, superset,
  mutually_exclusive, exhaustive, prerequisite, inverse, same_event_different_deadline,
  same_event_different_oracle, same_event_different_source, correlated_only, not_related

Research (Gebele & Matthes 2025) documented 1,501 equivalence classes and 1,645 subset
structures across 102,275 events on 10 platforms. Foundation Slice 1 will have hundreds of
nodes. Long-term scale: tens of thousands of events, hundreds of thousands of relations.

Neo4j is the graph-native benchmark for traversal performance and Cypher expressiveness.
PostgreSQL with adjacency table is viable for small-to-medium graphs with simple traversals.
PostgreSQL with Apache AGE extension adds Cypher syntax but is not optimized for deep traversals.
FalkorDB is a Redis-based alternative, less mature than Neo4j.

## Decision

Use **PostgreSQL with an adjacency table** in Foundation Slice 1, behind a `GraphRepository`
interface designed for the full 13-relation type set.

Migrate to **Neo4j** when any of the following triggers are hit:
- Node count exceeds 10,000
- Traversal queries require more than 3 hops
- Graph algorithm requirements emerge (PageRank, community detection, shortest path)

The `GraphRepository` interface must be designed around graph semantics (nodes, typed edges,
property queries, traversal), not SQL idioms. The backing store is an implementation detail.

## Alternatives considered

### Option A: PostgreSQL + adjacency table (chosen for Slice 1)

Pros:
- Single infrastructure component; no additional service in Slice 1
- Standard SQL; accessible to any developer familiar with PostgreSQL
- Sufficient for small-to-medium graphs with limited traversal depth
- Clean migration path to Neo4j when needed
- Lower operational overhead for a solo builder

Cons:
- Performance degrades for complex multi-hop queries at scale
- No native graph algorithms
- SQL adjacency joins are more verbose than Cypher for traversal queries

### Option B: Neo4j Community from day one

Pros:
- Graph-native; correct long-term choice
- Cypher syntax is expressive for relation queries
- No migration required later
- Native graph algorithms available immediately

Cons:
- Separate Docker service to operate from day one
- Neo4j Community edition memory and performance limits vs Enterprise
- Additional operational overhead when graph complexity in Slice 1 is low

### Option C: PostgreSQL + Apache AGE extension

Pros:
- Cypher queries within PostgreSQL
- Single infrastructure component with graph syntax

Cons:
- Not optimized for deep traversals — acts as a bridge, not a native graph
- Limited ecosystem and community compared to Neo4j
- Worst of both worlds at scale

### Option D: FalkorDB (Redis-based)

Pros:
- Fast for smaller graphs; lower memory footprint

Cons:
- Less mature ecosystem
- Introduces a third infrastructure component alongside PostgreSQL
- Redis operational model is different from relational databases

## Consequences

Positive:
- Minimal infrastructure complexity in Foundation Slice 1
- Full graph semantics expressed through the interface even when backed by SQL
- Migration to Neo4j is a clean, well-scoped operation when the trigger is hit

Negative:
- SQL adjacency queries are less expressive than Cypher
- Complex traversals will be verbose in early implementation

Neutral:
- Migration path: implement `Neo4jGraphRepository` behind `GraphRepository` interface,
  run data export/import script, switch dependency injection. Business logic untouched.

## Risks

- `GraphRepository` interface designed for SQL doesn't generalize to Neo4j's property graph
  model. Mitigate: design the interface around graph concepts — nodes, typed edges, property
  queries, traversal depth — not SQL-specific patterns.
- Graph grows faster than expected, triggering migration during active development.
  Mitigate: monitor node count actively; plan migration before hitting 10,000 nodes.
- Complex relation traversal queries become a performance bottleneck before the threshold.
  Mitigate: index relation type and market_id columns; add composite indexes for common
  traversal patterns.

## Rollback / revisit plan

Stay on PostgreSQL if: graph remains below 10,000 nodes and traversal queries stay shallow.
Migrate to Neo4j when the trigger threshold is hit. FalkorDB is an acceptable alternative
to Neo4j if the graph stays medium-sized and operational simplicity is a priority.

ADR to be superseded when Neo4j migration is decided.

## References

- Gebele & Matthes (2025): "Semantic Non-Fungibility and Violations of the Law of One Price
  in Prediction Markets" — https://arxiv.org/html/2601.01706v1
- Neo4j vs PostgreSQL comparison: https://pgbench.com/comparisons/postgres-vs-neo4j/
- Apache AGE extension: https://age.apache.org
- PARALLAX /idea analysis (2026-04-28)
- PARALLAX /research findings (2026-04-29)
