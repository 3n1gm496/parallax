from __future__ import annotations
from abc import ABC, abstractmethod
from parallax.shared.schemas import CounterexampleRecord, RelationType


class GraphRepository(ABC):
    """Read/write market-relation edges."""

    @abstractmethod
    def add_relation(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
        confidence: float,
        evidence: dict,
        created_by: str,
    ) -> str:
        """Persist a relation. Returns the new relation id."""
        ...

    @abstractmethod
    def get_relations(
        self,
        market_id: str,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        """Return all relations involving market_id (as either from or to)."""
        ...

    @abstractmethod
    def relation_exists(
        self,
        from_market_id: str,
        to_market_id: str,
        relation_type: RelationType,
    ) -> bool: ...

    @abstractmethod
    def delete_relation(self, relation_id: str) -> bool:
        """Delete a relation by id. Returns True if deleted, False if not found."""
        ...

    @abstractmethod
    def add_counterexample_record(self, record: CounterexampleRecord) -> str:
        """Persist a counterexample or proof-of-no-counterexample record."""
        ...

    @abstractmethod
    def add_relation_set(
        self,
        *,
        set_key: str,
        member_market_ids: list[str],
        relation_type: RelationType,
        confidence: float,
        evidence: dict,
        created_by: str,
    ) -> str:
        """Persist an n-ary relation set. Returns the new relation-set id."""
        ...

    @abstractmethod
    def get_relation_set(self, set_key: str) -> dict | None:
        """Return a persisted n-ary relation set by canonical set key."""
        ...

    @abstractmethod
    def list_relation_sets(
        self,
        *,
        limit: int = 100,
        relation_type: RelationType | None = None,
    ) -> list[dict]:
        """Return persisted n-ary relation sets."""
        ...
