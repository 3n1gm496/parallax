from __future__ import annotations

import re
import unicodedata
from datetime import datetime

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "in",
        "at",
        "on",
        "for",
        "by",
        "to",
        "is",
        "are",
        "will",
        "would",
        "could",
        "should",
        "does",
        "do",
        "be",
        "been",
        "being",
        "above",
        "below",
        "between",
        "from",
        "with",
        "without",
        "if",
        "than",
        "whether",
        "or",
        "and",
        "but",
        "not",
        "no",
        "yes",
        "its",
        "it",
        "who",
    ]
)

_SOURCE_ALIASES: dict[str, str] = {
    "associated press": "ap",
    "ap news": "ap",
    "reuters news": "reuters",
    "reuters": "reuters",
    "polymarket": "polymarket",
    "kalshi": "kalshi",
    "cme group": "cme",
    "cme": "cme",
    "cdc": "cdc",
    "centers for disease control": "cdc",
    "bls": "bls",
    "bureau of labor statistics": "bls",
    "fed": "federal_reserve",
    "federal reserve": "federal_reserve",
    "sec": "sec",
    "u.s. securities": "sec",
}


def _normalize_ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return normalized.encode("ascii", "ignore").decode("ascii")


class EntityNormalizer:
    def normalize(self, text: str) -> str:
        tokens = sorted(self.token_set(text))
        return " ".join(tokens)

    def token_set(self, text: str) -> set[str]:
        normalized = _normalize_ascii(text)
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return {token for token in normalized.split() if token not in _STOPWORDS and len(token) > 1}

    def jaccard(self, a: str, b: str) -> float:
        ta = self.token_set(a)
        tb = self.token_set(b)
        if not ta and not tb:
            return 1.0
        if not ta or not tb:
            return 0.0
        return round(len(ta & tb) / len(ta | tb), 4)


class SourceNormalizer:
    def normalize(self, source: str | None) -> str:
        if not source:
            return ""
        low = _normalize_ascii(source).strip()
        for alias, canonical in _SOURCE_ALIASES.items():
            if alias in low:
                return canonical
        cleaned = re.sub(r"[^a-z0-9]+", "_", low).strip("_")
        return cleaned[:100]


class DeadlineNormalizer:
    def normalize(self, deadline: datetime | None) -> str:
        if deadline is None:
            return "unknown"
        return deadline.strftime("%Y-%m-%d")

    def bucket(self, deadline: datetime | None) -> str:
        if deadline is None:
            return "unknown"
        quarter = (deadline.month - 1) // 3 + 1
        return f"{deadline.year}-Q{quarter}"

    def compatible(self, a: datetime | None, b: datetime | None, *, tolerance_hours: int = 24) -> bool:
        if a is None or b is None:
            return False
        return abs((a - b).total_seconds()) / 3600 <= tolerance_hours
