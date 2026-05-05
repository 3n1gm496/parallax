from __future__ import annotations

from sqlalchemy.orm import Session

from parallax.db.models import EventIdentityCluster, IdentityClusterMember, IdentityMatchReview, LogicalRelationSet, MarketEventLink
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.shared.schemas import IdentityResolutionStatus, RelationEvidenceResponse, RelationProof, RelationType


_IDENTITY_STATUS_PRIORITY = {
    IdentityResolutionStatus.REJECTED: 3,
    IdentityResolutionStatus.AMBIGUOUS: 2,
    IdentityResolutionStatus.UNRESOLVED: 1,
    IdentityResolutionStatus.VERIFIED: 0,
}


def load_relation_evidence(session: Session, market_ids: list[str]) -> RelationEvidenceResponse | None:
    if len(market_ids) < 2:
        return None
    relation_set = load_relation_set_evidence(session, market_ids)
    if relation_set is not None:
        return relation_set
    graph_repo = PostgresGraphRepository(session)
    anchor = market_ids[0]
    counterpart_ids = set(market_ids[1:])
    relation = next(
        (
            item
            for item in graph_repo.get_relations(anchor)
            if {item["from_market_id"], item["to_market_id"]} == {anchor, *counterpart_ids}
        ),
        None,
    )
    if relation is None:
        return None
    evidence = relation.get("evidence", {})
    identity_provenance = load_identity_provenance(session, market_ids)
    relation_proof = _build_relation_proof(
        relation_type=RelationType(relation["relation_type"]),
        evidence=evidence,
        confidence=relation["confidence"],
        created_by=relation["created_by"],
        identity_provenance=identity_provenance,
        from_market_id=relation["from_market_id"],
        to_market_id=relation["to_market_id"],
    )
    return RelationEvidenceResponse(
        from_market_id=relation["from_market_id"],
        to_market_id=relation["to_market_id"],
        relation_type=RelationType(relation["relation_type"]),
        is_confirmed=bool(evidence.get("is_confirmed", True)),
        confidence=relation["confidence"],
        created_by=relation["created_by"],
        evidence_version=evidence.get("evidence_version", "relation-analysis-v1"),
        abstention_reason=evidence.get("abstention_reason"),
        structural_relation_type=evidence.get("structural_relation_type"),
        semantic_relation_type=evidence.get("semantic_relation_type"),
        semantic_confidence=evidence.get("semantic_confidence"),
        semantic_reasoning=evidence.get("semantic_reasoning"),
        comparison_axes=evidence.get("comparison_axes", []),
        breaking_scenarios=evidence.get("breaking_scenarios", []),
        oracle_alignment=evidence.get("relation_signals", {}).get("oracle_alignment"),
        deadline_alignment=evidence.get("relation_signals", {}).get("deadline_alignment"),
        source_alignment=evidence.get("relation_signals", {}).get("source_alignment"),
        ambiguity_terms=evidence.get("relation_signals", {}).get("ambiguity_terms", []),
        relation_signals=evidence.get("relation_signals", {}),
        identity_provenance=identity_provenance,
        identity_status=load_identity_status(identity_provenance),
        identity_confidence=load_identity_confidence(identity_provenance),
        identity_version=load_identity_version(identity_provenance),
        identity_blocking_reason=load_identity_blocking_reason(identity_provenance),
        proof_status=evidence.get("proof_status", relation.get("proof_status", "verified")),
        tradeable_relation=bool(evidence.get("tradeable_relation", relation.get("tradeable_relation", False))),
        frame_id=evidence.get("frame_id", relation.get("frame_id")),
        set_key=evidence.get("set_key"),
        member_market_ids=evidence.get("member_market_ids", []),
        relation_proof=relation_proof,
    )


def load_relation_set_evidence(session: Session, market_ids: list[str]) -> RelationEvidenceResponse | None:
    set_key = "|".join(sorted(market_ids))
    row = session.query(LogicalRelationSet).filter(LogicalRelationSet.set_key == set_key).first()
    if row is None or not isinstance(getattr(row, "relation_type", None), str):
        return None
    evidence = row.evidence or {}
    identity_provenance = load_identity_provenance(session, market_ids)
    from_market_id = row.member_market_ids[0] if row.member_market_ids else market_ids[0]
    to_market_id = row.member_market_ids[1] if len(row.member_market_ids) > 1 else market_ids[-1]
    relation_proof = _build_relation_proof(
        relation_type=RelationType(row.relation_type),
        evidence=evidence,
        confidence=row.confidence,
        created_by=row.created_by,
        identity_provenance=identity_provenance,
        from_market_id=from_market_id,
        to_market_id=to_market_id,
    )
    return RelationEvidenceResponse(
        from_market_id=from_market_id,
        to_market_id=to_market_id,
        relation_type=RelationType(row.relation_type),
        is_confirmed=bool(evidence.get("is_confirmed", row.proof_status == "verified")),
        confidence=row.confidence,
        created_by=row.created_by,
        evidence_version=evidence.get("evidence_version", "relation-analysis-v1"),
        abstention_reason=evidence.get("abstention_reason"),
        structural_relation_type=evidence.get("structural_relation_type"),
        semantic_relation_type=evidence.get("semantic_relation_type"),
        semantic_confidence=evidence.get("semantic_confidence"),
        semantic_reasoning=evidence.get("semantic_reasoning"),
        comparison_axes=evidence.get("comparison_axes", []),
        breaking_scenarios=evidence.get("breaking_scenarios", []),
        oracle_alignment=evidence.get("relation_signals", {}).get("oracle_alignment"),
        deadline_alignment=evidence.get("relation_signals", {}).get("deadline_alignment"),
        source_alignment=evidence.get("relation_signals", {}).get("source_alignment"),
        ambiguity_terms=evidence.get("relation_signals", {}).get("ambiguity_terms", []),
        relation_signals=evidence.get("relation_signals", {}),
        identity_provenance=identity_provenance,
        identity_status=load_identity_status(identity_provenance),
        identity_confidence=load_identity_confidence(identity_provenance),
        identity_version=load_identity_version(identity_provenance),
        identity_blocking_reason=load_identity_blocking_reason(identity_provenance),
        proof_status=evidence.get("proof_status", row.proof_status),
        tradeable_relation=bool(evidence.get("tradeable_relation", row.tradeable_relation)),
        frame_id=evidence.get("frame_id", str(row.frame_id) if row.frame_id is not None else None),
        set_key=row.set_key,
        member_market_ids=list(row.member_market_ids or []),
        relation_proof=relation_proof,
    )


def load_identity_provenance(session: Session, market_ids: list[str]) -> dict[str, object] | None:
    links = (
        session.query(MarketEventLink)
        .filter(MarketEventLink.raw_market_id.in_(market_ids))
        .all()
    )
    if not isinstance(links, list) or not links:
        return None

    grouped: dict[str, list[MarketEventLink]] = {}
    for link in links:
        grouped.setdefault(str(link.canonical_event_id), []).append(link)

    shared = next(
        (
            (event_id, event_links)
            for event_id, event_links in grouped.items()
            if {link.raw_market_id for link in event_links} == set(market_ids)
        ),
        None,
    )
    if shared is None:
        return None

    event_id, event_links = shared
    cluster_ids = [
        str(cluster_id)
        for (cluster_id,) in (
            session.query(IdentityClusterMember.cluster_id)
            .filter(IdentityClusterMember.raw_market_id.in_(market_ids))
            .distinct()
            .all()
        )
    ]
    cluster_rows = (
        session.query(EventIdentityCluster)
        .filter(EventIdentityCluster.id.in_([cluster_id for cluster_id, in session.query(IdentityClusterMember.cluster_id).filter(IdentityClusterMember.raw_market_id.in_(market_ids)).distinct().all()]))
        .all()
        if cluster_ids
        else []
    )
    reviews = (
        session.query(IdentityMatchReview)
        .filter(IdentityMatchReview.raw_market_id.in_(market_ids))
        .all()
    )
    reviews_by_market = {row.raw_market_id: row for row in reviews}
    statuses = [
        _parse_identity_status(
            (reviews_by_market.get(link.raw_market_id).status if reviews_by_market.get(link.raw_market_id) else None)
            or (link.provenance or {}).get("identity_status")
        )
        for link in event_links
    ]
    aggregate_status = _max_identity_status(statuses)
    confidence_values = [
        _coerce_confidence(
            reviews_by_market.get(link.raw_market_id).score if reviews_by_market.get(link.raw_market_id) else None
        )
        or _coerce_confidence((link.provenance or {}).get("score"))
        for link in event_links
    ]
    blocking_reasons = [
        reason
        for link in event_links
        for reason in (
            (reviews_by_market.get(link.raw_market_id).review_payload or {}).get("review_reasons", [])
            if reviews_by_market.get(link.raw_market_id)
            else []
        )
        if aggregate_status != IdentityResolutionStatus.VERIFIED
    ]
    version = next(
        (
            str((reviews_by_market.get(link.raw_market_id).scorer_version))
            for link in event_links
            if reviews_by_market.get(link.raw_market_id) is not None
        ),
        None,
    ) or next(
        (
            str((link.provenance or {}).get("identity_version"))
            for link in event_links
            if (link.provenance or {}).get("identity_version")
        ),
        "identity-v1",
    )
    return {
        "canonical_event_id": event_id,
        "identity_status": aggregate_status.value,
        "identity_confidence": _average_confidence(confidence_values),
        "identity_version": version,
        "identity_blocking_reason": "; ".join(sorted(set(blocking_reasons))) if blocking_reasons else None,
        "cluster_ids": cluster_ids,
        "cluster_types": [cluster.identity_type for cluster in cluster_rows],
        "links": {
            link.raw_market_id: {
                "link_reason": link.link_reason,
                "provenance": link.provenance or {},
                "review_status": (
                    reviews_by_market.get(link.raw_market_id).status if reviews_by_market.get(link.raw_market_id) else None
                ),
                "review_score": (
                    reviews_by_market.get(link.raw_market_id).score if reviews_by_market.get(link.raw_market_id) else None
                ),
                "review_payload": (
                    reviews_by_market.get(link.raw_market_id).review_payload
                    if reviews_by_market.get(link.raw_market_id)
                    else None
                ),
            }
            for link in event_links
        },
    }


def load_identity_status(identity_provenance: dict[str, object] | None) -> IdentityResolutionStatus:
    return _parse_identity_status((identity_provenance or {}).get("identity_status"))


def load_identity_confidence(identity_provenance: dict[str, object] | None) -> float | None:
    return _coerce_confidence((identity_provenance or {}).get("identity_confidence"))


def load_identity_version(identity_provenance: dict[str, object] | None) -> str:
    return str((identity_provenance or {}).get("identity_version") or "identity-v1")


def load_identity_blocking_reason(identity_provenance: dict[str, object] | None) -> str | None:
    reason = (identity_provenance or {}).get("identity_blocking_reason")
    return str(reason) if reason else None


def _parse_identity_status(value: object) -> IdentityResolutionStatus:
    try:
        return IdentityResolutionStatus(str(value))
    except ValueError:
        return IdentityResolutionStatus.UNRESOLVED


def _coerce_confidence(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return None


def _average_confidence(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    if not valid:
        return None
    return round(sum(valid) / len(valid), 4)


def _build_relation_proof(
    *,
    relation_type: RelationType,
    evidence: dict[str, object],
    confidence: float,
    created_by: str,
    identity_provenance: dict[str, object] | None,
    from_market_id: str,
    to_market_id: str,
) -> RelationProof:
    return RelationProof(
        packet_id=f"relation:{from_market_id}:{to_market_id}",
        source_of_truth="primary_proof_based" if bool(evidence.get("tradeable_relation")) else "calibrated_model",
        fallback_status="none" if bool(evidence.get("tradeable_relation")) else "degraded",
        model_version=str(evidence.get("evidence_version", "relation-analysis-v1")),
        confidence=confidence,
        blocking_reason=evidence.get("abstention_reason"),
        counterexamples=evidence.get("breaking_scenarios", []) or [],
        evidence={
            **evidence,
            "created_by": created_by,
            "from_market_id": from_market_id,
            "to_market_id": to_market_id,
        },
        relation_type=relation_type,
        proof_status=str(evidence.get("proof_status", "verified")),
        tradeable_relation=bool(evidence.get("tradeable_relation", False)),
        relation_signals=evidence.get("relation_signals", {}),
        identity_provenance=identity_provenance,
        identity_status=load_identity_status(identity_provenance),
        identity_version=load_identity_version(identity_provenance),
        frame_id=evidence.get("frame_id"),
        set_key=evidence.get("set_key"),
        member_market_ids=list(evidence.get("member_market_ids", []) or []),
    )


def _max_identity_status(statuses: list[IdentityResolutionStatus]) -> IdentityResolutionStatus:
    if not statuses:
        return IdentityResolutionStatus.UNRESOLVED
    return max(statuses, key=lambda item: _IDENTITY_STATUS_PRIORITY[item])
