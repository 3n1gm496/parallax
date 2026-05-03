from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    @abstractmethod
    def similarity(self, a: str, b: str) -> float:
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        raise NotImplementedError


class TokenVectorProvider(EmbeddingProvider):
    _VERSION = "token-vector-v1"

    @property
    def version(self) -> str:
        return self._VERSION

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\b[a-z0-9]+\b", text.lower())

    def _tf(self, tokens: list[str]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        total = max(len(tokens), 1)
        return {token: count / total for token, count in counts.items()}

    def similarity(self, a: str, b: str) -> float:
        tokens_a = self._tokenize(a)
        tokens_b = self._tokenize(b)
        if not tokens_a or not tokens_b:
            return 0.0
        tf_a = self._tf(tokens_a)
        tf_b = self._tf(tokens_b)
        vocab = set(tf_a) | set(tf_b)
        dot = sum(tf_a.get(token, 0.0) * tf_b.get(token, 0.0) for token in vocab)
        mag_a = math.sqrt(sum(value * value for value in tf_a.values()))
        mag_b = math.sqrt(sum(value * value for value in tf_b.values()))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return round(dot / (mag_a * mag_b), 4)
