from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from parallax.db.models import IdentityBenchmarkCase, RawMarket
from parallax.identity.cluster_engine import ClusterEngine
from parallax.identity.embedding_provider import TokenVectorProvider


@dataclass
class BenchmarkDetail:
    case_key: str
    expected_label: str
    expected_identity_type: str
    actual_identity_type: str
    score: float
    correct: bool


@dataclass
class BenchmarkResult:
    total: int
    correct: int
    wrong: int
    skipped: int
    details: list[BenchmarkDetail] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.correct / self.total, 4)


class BenchmarkRunner:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._engine = ClusterEngine(session, embedding_provider=TokenVectorProvider())

    def evaluate_all(self) -> BenchmarkResult:
        cases = self._session.query(IdentityBenchmarkCase).all()
        correct = wrong = skipped = 0
        details: list[BenchmarkDetail] = []
        for case in cases:
            market_a = self._session.get(RawMarket, case.market_id_a)
            market_b = self._session.get(RawMarket, case.market_id_b)
            if market_a is None or market_b is None:
                skipped += 1
                continue
            actual_identity_type = self._engine.classify_pair(market_a, market_b)
            score = self._engine.score_pair(market_a, market_b)["score"]
            is_correct = actual_identity_type.value == case.expected_identity_type
            if is_correct:
                correct += 1
            else:
                wrong += 1
            details.append(
                BenchmarkDetail(
                    case_key=case.case_key,
                    expected_label=case.expected_label,
                    expected_identity_type=case.expected_identity_type,
                    actual_identity_type=actual_identity_type.value,
                    score=score,
                    correct=is_correct,
                )
            )
        return BenchmarkResult(total=len(cases), correct=correct, wrong=wrong, skipped=skipped, details=details)
