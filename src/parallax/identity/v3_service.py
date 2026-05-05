from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from parallax.db.models import CanonicalDeadline, CanonicalEntity, CanonicalEvent, CanonicalSource, EventTemplate, RawMarket
from parallax.identity.cluster_engine import ClusterEngine
from parallax.identity.cluster_repository import IdentityClusterRepository
from parallax.identity.event_repository import EventRepository
from parallax.identity.normalizer import DeadlineNormalizer, EntityNormalizer, SourceNormalizer
from parallax.shared.schemas import IdentityResolutionBundle, IdentityResolutionStatus, IdentityType


@dataclass(slots=True)
class IdentityV3Decision:
    canonical_event: CanonicalEvent
    status: IdentityResolutionStatus
    identity_type: IdentityType
    confidence: float
    provenance: dict[str, object]
    blocking_reasons: list[str]
    cluster_id: str | None = None
    resolution_bundle: IdentityResolutionBundle | None = None


class IdentityV3Service:
    VERSION = "identity-v3-runtime"

    def __init__(self, session: Session) -> None:
        self._session = session
        self._events = EventRepository(session)
        self._clusters = IdentityClusterRepository(session)
        self._engine = ClusterEngine(session)
        self._entity_normalizer = EntityNormalizer()
        self._source_normalizer = SourceNormalizer()
        self._deadline_normalizer = DeadlineNormalizer()

    def resolve_market(self, market: RawMarket) -> IdentityV3Decision:
        canonical_entity = self._upsert_entity(str(market.title))
        raw_source = market.resolution_source if isinstance(market.resolution_source, str) else market.platform
        canonical_source = self._upsert_source(str(raw_source))
        canonical_deadline = self._upsert_deadline(market.deadline)
        template = self._upsert_template(str(market.title))
        domain = market.category or market.platform

        if market.group_id:
            event, _ = self._get_or_create_event(
                name=str(market.title),
                domain=domain,
                platform_group_key=f"{market.platform}:{market.group_id}",
            )
            cluster = self._engine.find_or_create_singleton_cluster(event.id, market.id)
            bundle = self._build_resolution_bundle(
                market=market,
                retrieval_candidates=[
                    {
                        "candidate_event_id": str(event.id),
                        "candidate_event_name": event.name,
                        "score": 1.0,
                        "decision": "linked",
                        "reason": "platform-native group id match",
                    }
                ],
                rerank_result={
                    "selected_event_id": str(event.id),
                    "selected_score": 1.0,
                    "runner_up_score": None,
                },
                cluster_governance={
                    "cluster_id": str(cluster.id),
                    "governance_action": "singleton_init",
                    "status": "verified",
                },
                selected_cluster_id=str(cluster.id),
                unresolved_cluster_ids=[],
            )
            cluster.identity_type = IdentityType.DUPLICATE.value
            cluster.confidence = 1.0
            cluster.provenance = {
                "canonical_entity_id": str(canonical_entity.id),
                "canonical_source_id": str(canonical_source.id),
                "canonical_deadline_id": str(canonical_deadline.id),
                "event_template_id": str(template.id),
                "platform_group_match": True,
                "identity_version": self.VERSION,
                "blocking_reasons": [],
                "resolution_bundle": bundle.model_dump(mode="json"),
            }
            self._session.flush()
            return IdentityV3Decision(
                canonical_event=event,
                status=IdentityResolutionStatus.VERIFIED,
                identity_type=IdentityType.DUPLICATE,
                confidence=1.0,
                provenance=cluster.provenance,
                blocking_reasons=[],
                cluster_id=str(cluster.id),
                resolution_bundle=bundle,
            )

        active_events = self._events.list_active(domain=domain)
        comparisons: list[tuple[float, CanonicalEvent, RawMarket, IdentityType, dict[str, object]]] = []
        for event in active_events:
            linked_markets = self._events.list_markets_for_event(event.id)
            for linked_market in linked_markets:
                signals = self._engine.score_pair(market, linked_market)
                identity_type = self._engine.classify_pair(market, linked_market)
                provenance = {
                    **signals,
                    "identity_type": identity_type.value,
                    "canonical_entity_id": str(canonical_entity.id),
                    "canonical_source_id": str(canonical_source.id),
                    "canonical_deadline_id": str(canonical_deadline.id),
                    "event_template_id": str(template.id),
                    "normalized_source": self._source_normalizer.normalize(market.resolution_source or market.platform),
                    "normalized_deadline": self._deadline_normalizer.normalize(market.deadline),
                    "normalized_title": self._entity_normalizer.normalize(market.title),
                    "identity_version": self.VERSION,
                }
                comparisons.append((float(signals["score"]), event, linked_market, identity_type, provenance))

        if not comparisons:
            event, _ = self._get_or_create_event(name=str(market.title), domain=domain)
            cluster = self._engine.find_or_create_singleton_cluster(event.id, market.id)
            bundle = self._build_resolution_bundle(
                market=market,
                retrieval_candidates=[],
                rerank_result={
                    "selected_event_id": None,
                    "selected_score": 0.0,
                    "runner_up_score": None,
                },
                cluster_governance={
                    "cluster_id": str(cluster.id),
                    "governance_action": "singleton_init",
                    "status": "rejected",
                },
                selected_cluster_id=str(cluster.id),
                unresolved_cluster_ids=[str(cluster.id)],
            )
            cluster.confidence = 0.0
            cluster.identity_type = IdentityType.FALSE_EQUIVALENCE.value
            cluster.provenance = {
                "canonical_entity_id": str(canonical_entity.id),
                "canonical_source_id": str(canonical_source.id),
                "canonical_deadline_id": str(canonical_deadline.id),
                "event_template_id": str(template.id),
                "identity_version": self.VERSION,
                "blocking_reasons": ["no_candidate_cluster"],
                "resolution_bundle": bundle.model_dump(mode="json"),
            }
            self._session.flush()
            return IdentityV3Decision(
                canonical_event=event,
                status=IdentityResolutionStatus.UNRESOLVED,
                identity_type=IdentityType.FALSE_EQUIVALENCE,
                confidence=0.0,
                provenance=cluster.provenance,
                blocking_reasons=["no_candidate_cluster"],
                cluster_id=str(cluster.id),
                resolution_bundle=bundle,
            )

        comparisons.sort(key=lambda item: item[0], reverse=True)
        best_score, best_event, best_market, identity_type, provenance = comparisons[0]
        second_score = comparisons[1][0] if len(comparisons) > 1 else None
        blocking_reasons: list[str] = []
        status = IdentityResolutionStatus.VERIFIED

        if identity_type == IdentityType.FALSE_EQUIVALENCE:
            status = IdentityResolutionStatus.REJECTED
            blocking_reasons.append("false_equivalence")
        elif identity_type == IdentityType.CORRELATED:
            status = IdentityResolutionStatus.AMBIGUOUS
            blocking_reasons.append("correlated_only")
        elif second_score is not None and (best_score - second_score) < 0.08:
            status = IdentityResolutionStatus.AMBIGUOUS
            blocking_reasons.append("ambiguous_runner_up")
        elif best_score < 0.75:
            status = IdentityResolutionStatus.UNRESOLVED
            blocking_reasons.append("confidence_below_verified_floor")

        event = best_event if status == IdentityResolutionStatus.VERIFIED else self._get_or_create_event(
            name=str(market.title),
            domain=domain,
        )[0]
        cluster = self._engine.find_or_create_singleton_cluster(event.id, market.id)
        bundle = self._build_resolution_bundle(
            market=market,
            retrieval_candidates=[
                {
                    "candidate_event_id": str(candidate_event.id),
                    "candidate_event_name": candidate_event.name,
                    "score": float(score),
                    "decision": "linked" if candidate_event.id == best_event.id and status == IdentityResolutionStatus.VERIFIED else "rejected",
                    "reason": provenance.get("blocking_reasons", []),
                }
                for score, candidate_event, _, _, provenance in comparisons[:10]
            ],
            rerank_result={
                "selected_event_id": str(best_event.id) if status == IdentityResolutionStatus.VERIFIED else None,
                "selected_score": best_score,
                "runner_up_score": second_score,
                "identity_type": identity_type.value,
                "status": status.value,
            },
            cluster_governance={
                "cluster_id": str(cluster.id),
                "governance_action": "singleton_init" if status != IdentityResolutionStatus.VERIFIED else "merge_into_event",
                "status": status.value,
                "blocking_reasons": blocking_reasons,
            },
            selected_cluster_id=str(cluster.id),
            unresolved_cluster_ids=[str(cluster.id)] if status != IdentityResolutionStatus.VERIFIED else [],
        )
        cluster.identity_type = identity_type.value
        cluster.confidence = best_score
        cluster.provenance = {
            **provenance,
            "blocking_reasons": blocking_reasons,
            "matched_market_id": best_market.id,
            "matched_event_id": str(best_event.id),
            "runner_up_score": second_score,
            "resolution_bundle": bundle.model_dump(mode="json"),
        }
        self._session.flush()
        return IdentityV3Decision(
            canonical_event=event,
            status=status,
            identity_type=identity_type,
            confidence=best_score,
            provenance=cluster.provenance,
            blocking_reasons=blocking_reasons,
            cluster_id=str(cluster.id),
            resolution_bundle=bundle,
        )

    def review_cluster(
        self,
        cluster_id: str,
        *,
        action: str,
        reviewer: str,
        reason: str | None = None,
        evidence: dict | None = None,
    ) -> None:
        cluster = self._clusters.get_cluster(uuid.UUID(cluster_id))
        if cluster is None:
            raise ValueError(f"Cluster {cluster_id} not found")
        if action == "confirm":
            cluster.confidence = max(cluster.confidence, 0.9)
        elif action == "reject":
            cluster.confidence = min(cluster.confidence, 0.2)
            cluster.identity_type = IdentityType.FALSE_EQUIVALENCE.value
        elif action == "escalate":
            cluster.confidence = min(cluster.confidence, 0.6)
        cluster.provenance = {
            **(cluster.provenance or {}),
            "last_review_action": action,
            "last_review_reason": reason,
        }
        self._clusters.record_review_action(
            cluster_id=cluster.id,
            action=action,
            reviewer=reviewer,
            reason=reason,
            evidence=evidence,
        )
        self._session.flush()

    def _get_or_create_event(
        self,
        *,
        name: str,
        domain: str,
        platform_group_key: str | None = None,
    ) -> tuple[CanonicalEvent, bool]:
        if platform_group_key:
            existing = self._events.get_by_group_key(platform_group_key)
            if existing is not None:
                return existing, False
        event = self._events.create(name=name, domain=domain, platform_group_key=platform_group_key)
        self._session.flush()
        return event, True

    def _upsert_entity(self, text: str) -> CanonicalEntity:
        normalized = self._entity_normalizer.normalize(text)
        row = self._session.query(CanonicalEntity).filter_by(normalized_name=normalized).first()
        if row is None:
            row = CanonicalEntity(name=text, normalized_name=normalized, entity_type="event")
            self._session.add(row)
            self._session.flush()
        return row

    def _upsert_source(self, text: str) -> CanonicalSource:
        normalized = self._source_normalizer.normalize(text)
        row = self._session.query(CanonicalSource).filter_by(normalized_name=normalized).first()
        if row is None:
            row = CanonicalSource(name=text, normalized_name=normalized, source_type="oracle")
            self._session.add(row)
            self._session.flush()
        return row

    def _upsert_deadline(self, deadline) -> CanonicalDeadline:
        bucket_key = self._deadline_normalizer.bucket(deadline)
        row = self._session.query(CanonicalDeadline).filter_by(bucket_key=bucket_key).first()
        if row is None:
            row = CanonicalDeadline(bucket_key=bucket_key, resolution_date=deadline, deadline_type="bucket")
            self._session.add(row)
            self._session.flush()
        return row

    def _upsert_template(self, title: str) -> EventTemplate:
        tokens = sorted(self._entity_normalizer.token_set(title))
        family_key = "-".join(tokens[:6]) or "untitled"
        row = self._session.query(EventTemplate).filter_by(family_key=family_key).first()
        if row is None:
            row = EventTemplate(
                family_key=family_key,
                predicate_template=title,
                canonical_predicate=tokens[0] if tokens else "unknown",
                example_titles=[title],
            )
            self._session.add(row)
            self._session.flush()
        elif title not in (row.example_titles or []):
            row.example_titles = [*(row.example_titles or []), title][:10]
        return row

    @staticmethod
    def _build_resolution_bundle(
        *,
        market: RawMarket,
        retrieval_candidates: list[dict[str, object]],
        rerank_result: dict[str, object],
        cluster_governance: dict[str, object],
        selected_cluster_id: str | None,
        unresolved_cluster_ids: list[str],
    ) -> IdentityResolutionBundle:
        source_of_truth = "primary_proof_based" if rerank_result.get("selected_event_id") else "degraded_fallback"
        fallback_status = "none" if source_of_truth == "primary_proof_based" else "degraded"
        return IdentityResolutionBundle(
            packet_id=f"identity:{market.id}",
            source_of_truth=source_of_truth,
            fallback_status=fallback_status,
            model_version="identity-resolution-bundle-v1",
            confidence=float(rerank_result.get("selected_score") or 0.0),
            blocking_reason=(
                "; ".join(cluster_governance.get("blocking_reasons", []))
                if isinstance(cluster_governance.get("blocking_reasons"), list)
                else None
            ),
            evidence={
                "market_id": market.id,
                "platform": market.platform,
                "group_id": market.group_id,
            },
            candidate_retrieval={
                "query_market_id": market.id,
                "candidates": retrieval_candidates,
            },
            rerank_result=rerank_result,
            cluster_governance={
                **cluster_governance,
                "selected_cluster_id": selected_cluster_id,
            },
            resolved_cluster_ids=[selected_cluster_id] if selected_cluster_id else [],
            unresolved_cluster_ids=unresolved_cluster_ids,
        )
