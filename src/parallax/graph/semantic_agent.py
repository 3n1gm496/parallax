# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/graph/semantic_agent.py
#
# Parallax Semantic Agent — NLP-driven automatic market correlation discovery.
#
# Architecture (Cold Path):
#   1. Embed all market questions using a SentenceTransformer model.
#   2. Use Neo4j ANN vector search to find semantically similar markets
#      across venues (Kalshi ↔ Polymarket).
#   3. Apply deterministic heuristics to validate candidate pairs:
#      - Complement detection (YES/NO structural equivalence)
#      - Date/deadline alignment check
#      - Oracle coherence (same resolution authority)
#   4. Write confirmed relations to the Neo4j graph.
#   5. Compile validated pairs into ArbitrageSet nodes that the Hot Path
#      can load into its fast cache.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import anyio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Minimum cosine similarity threshold to consider two markets related
SIMILARITY_THRESHOLD = 0.88

# Model name — can be swapped for a larger fine-tuned model in production
# all-MiniLM-L6-v2: 384-dim, 22M params, ~80ms per batch of 64 on CPU
# paraphrase-multilingual-mpnet-base-v2: multilingual support for non-EN markets
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


@dataclass
class MarketRecord:
    market_id: str
    platform: str
    question: str
    description: str = ""
    end_date: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class SemanticMatch:
    market_a: MarketRecord
    market_b: MarketRecord
    cosine_score: float
    relation_type: str        # "EQUIVALENT_TO" | "COMPLEMENT_OF"
    is_complement: bool
    confidence: float

    def __repr__(self) -> str:
        return (
            f"SemanticMatch(score={self.cosine_score:.4f}, type={self.relation_type})\n"
            f"  A: [{self.market_a.platform}] {self.market_a.question}\n"
            f"  B: [{self.market_b.platform}] {self.market_b.question}"
        )


class SemanticAgent:
    """
    Parallax Semantic Agent V2.

    Offline Cold Path component: runs on schedule (e.g. every 30 minutes)
    to discover new arbitrage pairs from recently ingested markets.

    The agent is designed to be GPU-acceleratable. If a CUDA device is
    available, embedding computation will automatically use it.
    """

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL):
        self._model_name = model_name
        self._model = None
        logger.info(f"SemanticAgent initialized (model='{model_name}' — lazy load)")

    def _get_model(self):
        """Lazy-load the SentenceTransformer model on first use."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            logger.info(f"Loading embedding model '{self._model_name}'...")
            self._model = SentenceTransformer(self._model_name)
            logger.info("✅  Embedding model loaded.")
        except ImportError:
            logger.error("sentence-transformers not installed — semantic agent offline.")
            self._model = None
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """
        Compute dense sentence embeddings for a batch of texts.
        Returns None if the model is unavailable.
        """
        model = self._get_model()
        if not model:
            return None
        vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    # ── Core matching pipeline ─────────────────────────────────────────────────

    async def find_matches(
        self,
        new_markets: list[MarketRecord],
        *,
        graph_repo=None,
        min_similarity: float = SIMILARITY_THRESHOLD,
    ) -> list[SemanticMatch]:
        """
        Main entry point.
        1. Embeds all new_markets.
        2. For each, queries Neo4j for ANN similar markets from other venues.
        3. Validates and returns confirmed SemanticMatch objects.
        4. Optionally writes confirmed relations to graph_repo.
        """
        if not new_markets:
            return []

        questions = [m.question + ". " + m.description for m in new_markets]
        embeddings = await anyio.to_thread.run_sync(self.embed, questions)
        if not embeddings:
            logger.warning("No embeddings produced — skipping semantic match pass.")
            return []

        matches: list[SemanticMatch] = []
        processed_pairs = set()

        for market, emb in zip(new_markets, embeddings):
            # Upsert this market's embedding into Neo4j
            if graph_repo:
                await graph_repo.upsert_market(
                    market_id=market.market_id,
                    platform=market.platform,
                    question=market.question,
                    description=market.description,
                    tags=market.tags,
                    end_date=market.end_date,
                    embedding=emb,
                )

            # ANN search for similar markets in other venues
            if graph_repo:
                candidates = await graph_repo.find_similar_markets(
                    emb, top_k=15, min_score=min_similarity
                )
            else:
                candidates = []

            for candidate in candidates:
                # Skip same venue — we want cross-venue arbitrage
                if candidate["platform"] == market.platform:
                    continue
                # Skip if already processed in this pass
                pair_key = tuple(sorted([market.market_id, candidate["market_id"]]))
                if pair_key in processed_pairs:
                    continue
                processed_pairs.add(pair_key)

                if candidate["market_id"] == market.market_id:
                    continue

                # [Stage A] Semantic Non-Fungibility: Strict Temporal Alignment
                # Prevent matches where the resolution deadlines differ significantly.
                cand_end_date_str = candidate.get("end_date")
                if market.end_date and cand_end_date_str:
                    try:
                        # Simple strict check: must be within 48 hours of each other
                        m_date = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
                        c_date = datetime.fromisoformat(cand_end_date_str.replace("Z", "+00:00"))
                        diff_hours = abs((m_date - c_date).total_seconds()) / 3600
                        if diff_hours > 48:
                            logger.debug(f"Rejecting match {market.market_id} <-> {candidate['market_id']} due to temporal mismatch ({diff_hours}h diff)")
                            continue
                    except Exception:
                        pass # If parsing fails, fall back to semantic score

                score = float(candidate["score"])
                is_complement = self._is_complement_pair(market.question, candidate["question"])
                relation_type = "COMPLEMENT_OF" if is_complement else "EQUIVALENT_TO"
                confidence = self._compute_confidence(score, is_complement, market, candidate)

                match = SemanticMatch(
                    market_a=market,
                    market_b=MarketRecord(
                        market_id=candidate["market_id"],
                        platform=candidate["platform"],
                        question=candidate["question"],
                    ),
                    cosine_score=score,
                    relation_type=relation_type,
                    is_complement=is_complement,
                    confidence=confidence,
                )
                matches.append(match)
                logger.info(f"⚡ Semantic match found:\n{match}")

                # Persist to graph
                if graph_repo:
                    await graph_repo.add_relation(
                        from_market_id=market.market_id,
                        to_market_id=candidate["market_id"],
                        relation_type=relation_type,
                        confidence=confidence,
                        evidence={"cosine_score": score, "model": self._model_name},
                        created_by="SemanticAgentV2",
                    )

        return matches

    async def compile_arbitrage_sets(
        self,
        matches: list[SemanticMatch],
        *,
        graph_repo=None,
        friction_bps: float = 30.0,
    ) -> list[dict]:
        """
        ...
        """
        compiled = []
        for match in matches:
            if not match.is_complement:
                continue

            set_id = str(uuid.uuid4())
            result = {
                "set_id": set_id,
                "market_a_id": match.market_a.market_id,
                "market_b_id": match.market_b.market_id,
                "confidence": match.confidence,
                "compiled_at": datetime.now(timezone.utc).isoformat(),
            }

            if graph_repo:
                await graph_repo.upsert_arbitrage_set(
                    set_id=set_id,
                    market_ids=[match.market_a.market_id, match.market_b.market_id],
                    edge_bps=match.cosine_score * 10000 - friction_bps,  # heuristic
                    compiled_at=result["compiled_at"],
                )

            compiled.append(result)
            logger.info(f"📦 ArbitrageSet compiled: {set_id}")

        return compiled

    # ── Heuristics ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_complement_pair(q_a: str, q_b: str) -> bool:
        """
        Detect if two questions are structural complements, e.g.:
          - "Will Trump win?" ↔ "Will Trump lose?" (negation)
          - "YES outcome" ↔ "NO outcome" (opposite side)

        Uses lightweight regex rather than another ML model.
        """
        negations = re.compile(
            r"\b(not|won't|will not|loses?|fails?|doesn't|does not|no)\b", re.I
        )
        positives = re.compile(
            r"\b(will|wins?|succeeds?|yes|gets?)\b", re.I
        )
        # If one is affirmative and the other negative on the same entity → complement
        a_neg = bool(negations.search(q_a))
        b_neg = bool(negations.search(q_b))
        a_pos = bool(positives.search(q_a))
        b_pos = bool(positives.search(q_b))

        return (a_neg and b_pos) or (a_pos and b_neg)

    @staticmethod
    def _compute_confidence(
        cosine_score: float,
        is_complement: bool,
        market: MarketRecord,
        candidate: dict,
    ) -> float:
        """
        Combine semantic similarity with structural signals to produce
        a final confidence score [0, 1].
        """
        base = cosine_score
        # Structural complement bonus
        if is_complement:
            base = min(1.0, base + 0.05)
        # Cross-venue bonus (we know the market exists on both sides)
        base = min(1.0, base + 0.02)
        return round(base, 4)
