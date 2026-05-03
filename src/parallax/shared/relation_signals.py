from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from parallax.shared.schemas import AmbiguityFlag

RELATION_EVIDENCE_VERSION = "relation-analysis-v1"


def build_relation_signals(
    market_a,
    market_b,
    contract_a,
    contract_b,
) -> dict:
    ambiguity_a = _normalize_ambiguity_terms(getattr(contract_a, "ambiguity_terms", []))
    ambiguity_b = _normalize_ambiguity_terms(getattr(contract_b, "ambiguity_terms", []))
    all_ambiguity_terms = sorted(set(ambiguity_a + ambiguity_b))
    shared_ambiguity_terms = sorted(set(ambiguity_a) & set(ambiguity_b))
    ambiguity_count = len(ambiguity_a) + len(ambiguity_b)

    deadline_a = getattr(market_a, "deadline", None)
    deadline_b = getattr(market_b, "deadline", None)
    if isinstance(deadline_a, datetime) and isinstance(deadline_b, datetime):
        deadline_delta_hours = abs((deadline_a - deadline_b).total_seconds()) / 3600
    else:
        deadline_delta_hours = 0.0
    source_a = _normalized_source(market_a.resolution_source)
    source_b = _normalized_source(market_b.resolution_source)
    source_mismatch = source_a != source_b
    oracle_mismatch = source_mismatch and bool(source_a and source_b)
    deadline_mismatch = deadline_delta_hours >= 24
    return {
        "cross_platform": market_a.platform != market_b.platform,
        "oracle_mismatch": oracle_mismatch,
        "oracle_alignment": "mismatch" if oracle_mismatch else "aligned",
        "source_mismatch": source_mismatch,
        "source_alignment": "mismatch" if source_mismatch else "aligned",
        "deadline_delta_hours": round(deadline_delta_hours, 2),
        "deadline_mismatch": deadline_mismatch,
        "deadline_alignment": "mismatch" if deadline_mismatch else "aligned",
        "ambiguity_count": ambiguity_count,
        "ambiguity_terms": all_ambiguity_terms,
        "shared_ambiguity_terms": shared_ambiguity_terms,
        "ambiguity_level": _ambiguity_level(ambiguity_count, len(shared_ambiguity_terms)),
    }


def get_relation_signals(relation) -> dict:
    if relation is None:
        return {
            "cross_platform": False,
            "oracle_mismatch": False,
            "oracle_alignment": "aligned",
            "source_mismatch": False,
            "source_alignment": "aligned",
            "deadline_delta_hours": 0.0,
            "deadline_mismatch": False,
            "deadline_alignment": "aligned",
            "ambiguity_count": 0,
            "ambiguity_terms": [],
            "shared_ambiguity_terms": [],
            "ambiguity_level": "low",
        }
    if hasattr(relation, "relation_signals"):
        signals = getattr(relation, "relation_signals", {}) or {}
    else:
        signals = relation.get("evidence", {}).get("relation_signals", {})
    return {
        "cross_platform": bool(signals.get("cross_platform", False)),
        "oracle_mismatch": bool(signals.get("oracle_mismatch", False)),
        "oracle_alignment": str(signals.get("oracle_alignment", "aligned")),
        "source_mismatch": bool(signals.get("source_mismatch", False)),
        "source_alignment": str(signals.get("source_alignment", "aligned")),
        "deadline_delta_hours": float(signals.get("deadline_delta_hours", 0.0)),
        "deadline_mismatch": bool(signals.get("deadline_mismatch", False)),
        "deadline_alignment": str(signals.get("deadline_alignment", "aligned")),
        "ambiguity_count": int(signals.get("ambiguity_count", 0)),
        "ambiguity_terms": list(signals.get("ambiguity_terms", [])),
        "shared_ambiguity_terms": list(signals.get("shared_ambiguity_terms", [])),
        "ambiguity_level": str(signals.get("ambiguity_level", "low")),
    }


def _normalize_ambiguity_terms(terms: Iterable[AmbiguityFlag | dict]) -> list[str]:
    normalized: list[str] = []
    for term in terms:
        if isinstance(term, AmbiguityFlag):
            normalized.append(term.term.strip().lower())
        elif isinstance(term, dict) and isinstance(term.get("term"), str):
            normalized.append(term["term"].strip().lower())
    return normalized


def _normalized_source(source: str | None) -> str:
    return source.strip().lower() if isinstance(source, str) and source.strip() else ""


def _ambiguity_level(ambiguity_count: int, shared_count: int) -> str:
    if ambiguity_count >= 4 or shared_count >= 2:
        return "high"
    if ambiguity_count >= 2 or shared_count >= 1:
        return "medium"
    return "low"
