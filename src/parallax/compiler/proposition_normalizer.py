from __future__ import annotations

import re
from datetime import datetime

from parallax.shared.schemas import CompiledPropositionSchema, ContractSchema


def build_compiled_proposition(market, contract: ContractSchema, *, raw_market_id: str) -> CompiledPropositionSchema:
    title = _normalize_text(getattr(market, "title", "") or "")
    description = _normalize_text(getattr(market, "description", "") or "")
    criteria = _normalize_text(getattr(market, "resolution_criteria", "") or "")
    source_text = " ".join(part for part in [title, description, criteria] if part)

    canonical_subject = contract.canonical_subject or _canonical_subject(title)
    canonical_predicate = contract.canonical_predicate or _canonical_predicate(title)
    canonical_object = contract.canonical_object or _canonical_object(title, criteria)
    comparator = contract.comparator or _comparator(source_text)
    threshold_value = contract.threshold_value or _threshold_value(source_text)
    temporal_focus = contract.temporal_focus or _temporal_focus(title, criteria)
    temporal_deadline = contract.temporal_deadline or _deadline(getattr(market, "deadline", None))
    oracle_focus = contract.oracle_focus or _oracle_focus(getattr(market, "resolution_source", None), getattr(market, "platform", None))
    time_scope = contract.time_scope or temporal_deadline or temporal_focus
    oracle_scope = contract.oracle_scope or oracle_focus
    proposition_family = contract.proposition_family or _proposition_family(title)
    partition_hint = contract.partition_hint or _partition_hint(title, source_text)
    semantic_tags = sorted(set(contract.semantic_tags or []) | _semantic_tags(title, criteria))
    resolution_exclusions = list(contract.resolution_exclusions or contract.exclusions or [])
    cancellation_conditions = list(contract.cancellation_conditions or _cancellation_conditions(source_text))
    polarity = contract.polarity if contract.polarity != "unknown" else _polarity(canonical_predicate)

    return CompiledPropositionSchema(
        raw_market_id=raw_market_id,
        canonical_subject=canonical_subject,
        canonical_predicate=canonical_predicate,
        canonical_object=canonical_object,
        comparator=comparator,
        threshold_value=threshold_value,
        threshold_comparator=contract.threshold_comparator or comparator,
        threshold=contract.threshold or threshold_value,
        temporal_focus=temporal_focus,
        temporal_deadline=temporal_deadline,
        time_scope=time_scope,
        oracle_focus=oracle_focus,
        oracle_scope=oracle_scope,
        resolution_exclusions=resolution_exclusions,
        cancellation_conditions=cancellation_conditions,
        polarity=polarity,
        proposition_family=proposition_family,
        partition_hint=partition_hint,
        semantic_tags=semantic_tags,
        compiler_confidence=contract.compiler_confidence,
    )


def enrich_contract(contract: ContractSchema, proposition: CompiledPropositionSchema) -> ContractSchema:
    return contract.model_copy(
        update={
            "canonical_subject": proposition.canonical_subject,
            "canonical_predicate": proposition.canonical_predicate,
            "canonical_object": proposition.canonical_object,
            "comparator": proposition.comparator,
            "threshold_value": proposition.threshold_value,
            "threshold_comparator": proposition.threshold_comparator,
            "threshold": proposition.threshold,
            "temporal_focus": proposition.temporal_focus,
            "temporal_deadline": proposition.temporal_deadline,
            "time_scope": proposition.time_scope,
            "oracle_focus": proposition.oracle_focus,
            "oracle_scope": proposition.oracle_scope,
            "resolution_exclusions": proposition.resolution_exclusions,
            "cancellation_conditions": proposition.cancellation_conditions,
            "polarity": proposition.polarity,
            "proposition_family": proposition.proposition_family,
            "partition_hint": proposition.partition_hint,
            "semantic_tags": proposition.semantic_tags,
        }
    )


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _canonical_subject(title: str) -> str:
    lowered = title.lower()
    if lowered.startswith("who will "):
        return "who"
    if lowered.startswith("will "):
        return title[5:].split(" before ")[0].split(" by ")[0].strip(" ?") or title
    return title.strip(" ?")


def _canonical_predicate(title: str) -> str:
    lowered = title.lower()
    if lowered.startswith("who will "):
        return "selection"
    if " before " in lowered:
        return "before_event"
    if " by " in lowered:
        return "by_deadline"
    if lowered.startswith("will "):
        return "binary_occurrence"
    return "market_resolution"


def _canonical_object(title: str, criteria: str) -> str | None:
    lowered = title.lower()
    if lowered.startswith("who will "):
        return title[9:].strip(" ?")
    match = re.search(r"before ([^?]+)", title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r"if ([^.]+)", criteria, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _comparator(text: str) -> str | None:
    lowered = text.lower()
    for token in ("less than", "greater than", "at least", "at most", "before", "after", "by"):
        if token in lowered:
            return token.replace(" ", "_")
    return None


def _threshold_value(text: str) -> str | None:
    match = re.search(r"(\$?\d[\d,]*(?:\.\d+)?)", text)
    return match.group(1) if match else None


def _temporal_focus(title: str, criteria: str) -> str | None:
    lowered = f"{title} {criteria}".lower()
    if "before" in lowered:
        return "before"
    if "after" in lowered:
        return "after"
    if "by " in lowered:
        return "by"
    return None


def _deadline(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _oracle_focus(source: str | None, platform: str | None) -> str:
    if isinstance(source, str) and source.strip():
        return source.strip().lower()
    return f"platform_default:{platform or 'unknown'}"


def _proposition_family(title: str) -> str:
    lowered = title.lower().strip(" ?")
    lowered = re.sub(r"\bwill\b", "", lowered)
    lowered = re.sub(r"\bwho\b", "", lowered)
    lowered = re.sub(r"\d+\b", "<num>", lowered)
    lowered = re.sub(r"\b[a-z]{1,2}\b", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    match = re.search(r"before ([^?]+)", lowered)
    if match:
        return f"before::{match.group(1).strip()}"
    return lowered


def _partition_hint(title: str, text: str) -> bool:
    lowered = f"{title} {text}".lower()
    return any(
        pattern in lowered
        for pattern in (
            "who will",
            "which candidate",
            "first person elected",
            "next pope",
            "next president",
            "nominee",
        )
    )


def _semantic_tags(title: str, criteria: str) -> set[str]:
    lowered = f"{title} {criteria}".lower()
    tags: set[str] = set()
    if "before" in lowered or "after" in lowered or " by " in lowered:
        tags.add("temporal")
    if "who will" in lowered or "next " in lowered:
        tags.add("selection")
    if "if " in lowered:
        tags.add("conditional")
    if "unless" in lowered or "excluding" in lowered:
        tags.add("exclusionary")
    return tags


def _cancellation_conditions(text: str) -> list[str]:
    lowered = text.lower()
    conditions: list[str] = []
    for token in ("cancel", "cancelled", "void", "voided", "invalid", "refund"):
        if token in lowered:
            conditions.append(token)
    return sorted(set(conditions))


def _polarity(predicate: str | None) -> str:
    if not predicate:
        return "unknown"
    return "negative" if predicate.startswith("not_") else "positive"
