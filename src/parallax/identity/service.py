from __future__ import annotations
import re
import uuid
from sqlalchemy.orm import Session
from parallax.audit.service import AuditService
from parallax.db.models import CanonicalEvent, EventIdentityCluster, IdentityMatchReview, MarketEventLink
from parallax.identity.cluster_engine import ClusterEngine
from parallax.identity.cluster_repository import IdentityClusterRepository
from parallax.identity.event_repository import EventRepository
from parallax.identity.v3_service import IdentityV3Service
from parallax.ingestion.market_repository import MarketRepository
from parallax.shared.schemas import IdentityResolutionStatus


_IDENTITY_SCORER_VERSION = "identity-v3"
_IDENTITY_MIN_VERIFIED_SCORE = 0.75
_IDENTITY_AMBIGUITY_GAP = 0.1


class IdentityService:
    """Resolve raw markets to canonical events and manage market-event links."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = EventRepository(session)
        self._market_repo = MarketRepository(session)
        self._audit = AuditService(session)
        self._cluster_engine = ClusterEngine(session)
        self._cluster_repo = IdentityClusterRepository(session)
        self._v3 = IdentityV3Service(session)

    def get_or_create_event(
        self,
        name: str,
        domain: str,
        platform_group_key: str | None = None,
    ) -> tuple[CanonicalEvent, bool]:
        """Return (event, created). Looks up by group key if provided."""
        if platform_group_key:
            existing = self._repo.get_by_group_key(platform_group_key)
            if existing:
                return existing, False
        event = self._repo.create(name, domain, platform_group_key)
        self._session.flush()
        self._audit.record(
            "identity.event.created",
            "canonical_event",
            str(event.id),
            {
                "name": name,
                "domain": domain,
                "platform_group_key": platform_group_key,
            },
        )
        return event, True

    def link_market(
        self,
        raw_market_id: str,
        canonical_event_id: uuid.UUID,
        link_reason: str = "platform_group_key",
        provenance: dict | None = None,
    ) -> MarketEventLink | None:
        """Link a raw market to a canonical event. Returns None if already linked."""
        existing = self._session.get(
            MarketEventLink, (raw_market_id, canonical_event_id)
        )
        if existing:
            return None
        link = MarketEventLink(
            raw_market_id=raw_market_id,
            canonical_event_id=canonical_event_id,
            link_reason=link_reason,
            provenance=provenance or {},
        )
        self._session.add(link)
        self._session.flush()
        self._audit.record(
            "identity.market.linked",
            "raw_market",
            raw_market_id,
            {
                "canonical_event_id": str(canonical_event_id),
                "link_reason": link_reason,
                "provenance": provenance or {},
            },
        )
        return link

    def get_events_for_market(self, raw_market_id: str) -> list[CanonicalEvent]:
        links = (
            self._session.query(MarketEventLink)
            .filter_by(raw_market_id=raw_market_id)
            .all()
        )
        return [
            self._repo.get(link.canonical_event_id)
            for link in links
            if self._repo.get(link.canonical_event_id) is not None
        ]

    def resolve_all_ungrouped(self) -> int:
        """Attach unlinked grouped markets to canonical events.

        Current identity resolution is intentionally conservative: it only links
        markets that already carry a platform-native grouping key.
        """
        touched_event_ids: set[uuid.UUID] = set()
        for market in self._market_repo.list_unlinked_open():
            domain = market.category or market.platform
            provenance = self._base_provenance(market)
            link_reason = "new_event"

            runtime_decision = self._v3.resolve_market(market)

            if market.group_id:
                event, _ = self.get_or_create_event(
                    name=market.title,
                    domain=domain,
                    platform_group_key=f"{market.platform}:{market.group_id}",
                )
                link_reason = "platform_group_key"
                provenance.update(
                    {
                        "platform_group_match": True,
                        "decision": "linked",
                        "score": 1.0,
                        "identity_type": runtime_decision.identity_type.value,
                        "identity_cluster_id": runtime_decision.cluster_id,
                        "identity_status": IdentityResolutionStatus.VERIFIED.value,
                        "identity_version": runtime_decision.provenance.get("identity_version", _IDENTITY_SCORER_VERSION),
                        "cluster_ids": [runtime_decision.cluster_id] if runtime_decision.cluster_id else [],
                        "identity_resolution_bundle": (
                            runtime_decision.resolution_bundle.model_dump(mode="json")
                            if runtime_decision.resolution_bundle is not None
                            else None
                        ),
                    }
                )
                self._record_identity_review(
                    raw_market_id=market.id,
                    canonical_event_id=event.id,
                    status=IdentityResolutionStatus.VERIFIED,
                    score=1.0,
                    review_payload={
                        **provenance,
                        "scorer_version": _IDENTITY_SCORER_VERSION,
                        "selected_candidate_id": str(event.id),
                        "selected_candidate_score": 1.0,
                        "review_reasons": ["platform-native group id match"],
                        "alternatives": [],
                        "identity_resolution_bundle": (
                            runtime_decision.resolution_bundle.model_dump(mode="json")
                            if runtime_decision.resolution_bundle is not None
                            else None
                        ),
                    },
                )
            else:
                review = self._match_existing_event(market, domain)
                if runtime_decision.status == IdentityResolutionStatus.VERIFIED:
                    event = runtime_decision.canonical_event
                    link_reason = "identity_v3_runtime_authority"
                    provenance.update(
                        {
                            **runtime_decision.provenance,
                            "decision": "linked",
                            "score": runtime_decision.confidence,
                            "identity_status": runtime_decision.status.value,
                            "identity_type": runtime_decision.identity_type.value,
                            "identity_cluster_id": runtime_decision.cluster_id,
                            "cluster_ids": [runtime_decision.cluster_id] if runtime_decision.cluster_id else [],
                            "identity_resolution_bundle": (
                                runtime_decision.resolution_bundle.model_dump(mode="json")
                                if runtime_decision.resolution_bundle is not None
                                else None
                            ),
                        }
                    )
                    self._record_identity_review(
                        raw_market_id=market.id,
                        canonical_event_id=event.id,
                        status=runtime_decision.status,
                        score=runtime_decision.confidence,
                        review_payload={
                            **runtime_decision.provenance,
                            "status": runtime_decision.status.value,
                            "identity_type": runtime_decision.identity_type.value,
                            "review_reasons": runtime_decision.blocking_reasons,
                            "selected_candidate_id": str(event.id),
                            "selected_candidate_score": runtime_decision.confidence,
                            "cluster_id": runtime_decision.cluster_id,
                            "identity_resolution_bundle": (
                                runtime_decision.resolution_bundle.model_dump(mode="json")
                                if runtime_decision.resolution_bundle is not None
                                else None
                            ),
                        },
                    )
                elif review["selected_event"] is None:
                    event, _ = self.get_or_create_event(name=market.title, domain=domain)
                    provenance.update(
                        {
                            "decision": "created_new_event",
                            "score": 0.0,
                            "identity_status": runtime_decision.status.value,
                            "identity_version": runtime_decision.provenance.get("identity_version", _IDENTITY_SCORER_VERSION),
                            "identity_type": runtime_decision.identity_type.value,
                            "identity_cluster_id": runtime_decision.cluster_id,
                            "identity_blocking_reason": "; ".join(runtime_decision.blocking_reasons) if runtime_decision.blocking_reasons else None,
                            "cluster_ids": [runtime_decision.cluster_id] if runtime_decision.cluster_id else [],
                            "identity_resolution_bundle": (
                                runtime_decision.resolution_bundle.model_dump(mode="json")
                                if runtime_decision.resolution_bundle is not None
                                else None
                            ),
                        }
                    )
                    self._record_identity_review(
                        raw_market_id=market.id,
                        canonical_event_id=None,
                        status=runtime_decision.status,
                        score=0.0,
                        review_payload={
                            **runtime_decision.provenance,
                            "status": runtime_decision.status.value,
                            "identity_type": runtime_decision.identity_type.value,
                            "review_reasons": runtime_decision.blocking_reasons,
                            "created_new_event": True,
                            "created_event_id": str(event.id),
                            "cluster_id": runtime_decision.cluster_id,
                            "identity_resolution_bundle": (
                                runtime_decision.resolution_bundle.model_dump(mode="json")
                                if runtime_decision.resolution_bundle is not None
                                else None
                            ),
                        },
                    )
                else:
                    event = review["selected_event"]
                    provenance.update(
                        {
                            **review["selected_provenance"],
                            **runtime_decision.provenance,
                            "identity_type": runtime_decision.identity_type.value,
                            "identity_cluster_id": runtime_decision.cluster_id,
                            "cluster_ids": [runtime_decision.cluster_id] if runtime_decision.cluster_id else [],
                            "identity_resolution_bundle": (
                                runtime_decision.resolution_bundle.model_dump(mode="json")
                                if runtime_decision.resolution_bundle is not None
                                else None
                            ),
                        }
                    )
                    link_reason = "multi_signal_match"
                    self._record_identity_review(
                        raw_market_id=market.id,
                        canonical_event_id=event.id,
                        status=runtime_decision.status if runtime_decision.status != IdentityResolutionStatus.VERIFIED else review["status"],
                        score=review["selected_score"] if review["selected_score"] is not None else runtime_decision.confidence,
                        review_payload={
                            **review["payload"],
                            "identity_type": runtime_decision.identity_type.value,
                            "cluster_id": runtime_decision.cluster_id,
                            "blocking_reasons": runtime_decision.blocking_reasons,
                            "identity_resolution_bundle": (
                                runtime_decision.resolution_bundle.model_dump(mode="json")
                                if runtime_decision.resolution_bundle is not None
                                else None
                            ),
                        },
                    )

            link = self.link_market(
                market.id,
                event.id,
                link_reason=link_reason,
                provenance=provenance,
            )
            if runtime_decision.cluster_id:
                provenance["cluster_ids"] = [runtime_decision.cluster_id]
            self._resolve_with_cluster(
                market,
                event.id,
                link_reason=link_reason,
                score=runtime_decision.confidence if runtime_decision.confidence is not None else (review["selected_score"] if "review" in locals() and review.get("selected_score") is not None else 1.0),
                signals=provenance,
            )
            if link is not None:
                touched_event_ids.add(event.id)
                self._audit.record(
                    "identity.market.resolved",
                    "raw_market",
                    market.id,
                    {
                        "canonical_event_id": str(event.id),
                        "platform": market.platform,
                        "group_id": market.group_id,
                        "domain": domain,
                        "link_reason": link_reason,
                        "provenance": provenance,
                    },
                )
                # BUG-031: Checkpoint commit to avoid losing progress on large batches
                self._session.commit()
        return len(touched_event_ids)

    def _record_identity_review(
        self,
        *,
        raw_market_id: str,
        canonical_event_id: uuid.UUID | None,
        status: IdentityResolutionStatus,
        score: float | None,
        review_payload: dict,
    ) -> None:
        row = (
            self._session.query(IdentityMatchReview)
            .filter(IdentityMatchReview.raw_market_id == raw_market_id)
            .first()
        )
        if row is None:
            row = IdentityMatchReview(raw_market_id=raw_market_id)
            self._session.add(row)
        row.canonical_event_id = canonical_event_id
        row.status = status.value
        row.score = score
        row.scorer_version = _IDENTITY_SCORER_VERSION
        row.review_payload = review_payload
        self._session.flush()

    def _resolve_with_cluster(
        self,
        market,
        canonical_event_id: uuid.UUID,
        *,
        link_reason: str,
        score: float,
        signals: dict,
    ) -> None:
        cluster = self._cluster_engine.find_or_create_singleton_cluster(
            canonical_event_id=canonical_event_id,
            raw_market_id=market.id,
        )
        candidate_clusters = (
            self._session.query(EventIdentityCluster)
            .filter(EventIdentityCluster.status == "active", EventIdentityCluster.id != cluster.id)
            .all()
        )
        decision = self._cluster_engine.find_best_cluster_match(market, candidate_clusters)
        if decision is None:
            return
        self._cluster_engine.add_member_to_cluster(
            decision.cluster_id,
            canonical_event_id,
            market.id,
            evidence={
                **decision.provenance,
                "link_reason": link_reason,
                "legacy_score": score,
                "legacy_signals": signals,
            },
        )

    def _match_existing_event(self, market, domain: str) -> dict:
        candidates: list[tuple[float, CanonicalEvent, dict]] = []
        for event in self._repo.list_active(domain=domain):
            linked_markets = self._repo.list_markets_for_event(event.id)
            if not linked_markets:
                continue
            best = max(
                (self._compare_market_pair(market, linked_market) for linked_market in linked_markets),
                key=lambda item: item["score"],
            )
            candidates.append((best["score"], event, best))

        ranked_candidates = [
            {
                **candidate,
                "canonical_event_id": str(event.id),
                "canonical_event_name": event.name,
                "decision": candidate["decision"],
            }
            for score, event, candidate in sorted(candidates, key=lambda item: item[0], reverse=True)
            if score > 0
        ]

        if not ranked_candidates:
            return {
                "selected_event": None,
                "selected_score": 0.0,
                "selected_provenance": {},
                "status": IdentityResolutionStatus.UNRESOLVED,
                "payload": {
                    "market_id": market.id,
                    "status": IdentityResolutionStatus.UNRESOLVED.value,
                    "scorer_version": _IDENTITY_SCORER_VERSION,
                    "selected_candidate_id": None,
                    "selected_candidate_score": 0.0,
                    "review_reasons": ["no viable canonical event candidate found"],
                    "alternatives": [],
                },
            }

        top_candidate = ranked_candidates[0]
        top_score = float(top_candidate["score"])
        second_score = float(ranked_candidates[1]["score"]) if len(ranked_candidates) > 1 else None
        if top_candidate["decision"] != "linked":
            status = IdentityResolutionStatus.UNRESOLVED
            selected_event = None
            selected_provenance: dict = {}
            review_reasons = ["top candidate failed compatibility checks"]
        elif second_score is not None and (top_score - second_score) < _IDENTITY_AMBIGUITY_GAP:
            status = IdentityResolutionStatus.AMBIGUOUS
            selected_event = None
            selected_provenance = {}
            review_reasons = ["top candidate too close to runner-up"]
        elif top_score < _IDENTITY_MIN_VERIFIED_SCORE:
            status = IdentityResolutionStatus.UNRESOLVED
            selected_event = None
            selected_provenance = {}
            review_reasons = ["top candidate score below verification floor"]
        else:
            status = IdentityResolutionStatus.VERIFIED
            selected_event = next(
                event for _, event, _ in candidates if str(event.id) == top_candidate["canonical_event_id"]
            )
            selected_provenance = {
                **top_candidate,
                "identity_status": status.value,
                "identity_version": _IDENTITY_SCORER_VERSION,
                "runner_up_score": second_score,
            }
            review_reasons = ["top candidate passed compatibility and score thresholds"]

        return {
            "selected_event": selected_event,
            "selected_score": top_score,
            "selected_provenance": selected_provenance,
            "status": status,
            "payload": {
                "market_id": market.id,
                "status": status.value,
                "scorer_version": _IDENTITY_SCORER_VERSION,
                "selected_candidate_id": top_candidate["canonical_event_id"] if status == IdentityResolutionStatus.VERIFIED else None,
                "selected_candidate_score": top_score,
                "review_reasons": review_reasons,
                "alternatives": ranked_candidates,
            },
        }

    def _compare_market_pair(self, market, linked_market) -> dict:
        market_tokens = self._title_tokens(market.title)
        linked_tokens = self._title_tokens(linked_market.title)
        shared_tokens = sorted(market_tokens & linked_tokens)
        union_count = len(market_tokens | linked_tokens) or 1
        lexical_similarity = round(len(shared_tokens) / union_count, 4)
        deadline_delta_hours = round(
            abs((market.deadline - linked_market.deadline).total_seconds()) / 3600,
            2,
        )
        # [LOGIC FIX L-010] Relative Deadline Compatibility
        # For markets with < 48h to expiry, the gap must be < 4h.
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        time_to_expiry_market = (market.deadline - now).total_seconds() / 3600
        
        if time_to_expiry_market < 48:
            deadline_compatible = deadline_delta_hours <= 4
        else:
            deadline_compatible = deadline_delta_hours <= 24
        # BUG-027 Fix: Do not allow empty sources to match everything. 
        # Source must be aligned or both must be empty (which is discouraged).
        m_source = self._normalized_source(market.resolution_source)
        l_source = self._normalized_source(linked_market.resolution_source)
        
        if m_source == "" or l_source == "":
            source_compatible = (m_source == l_source)
        else:
            source_compatible = (m_source == l_source)
        entity_overlap = len(shared_tokens)
        platform_group_match = bool(
            market.group_id and linked_market.group_id and market.group_id == linked_market.group_id
        )
        score = round(
            lexical_similarity * 0.55
            + (0.2 if deadline_compatible else 0.0)
            + (0.15 if source_compatible else 0.0)
            + min(entity_overlap, 4) * 0.025
            + (0.1 if platform_group_match else 0.0),
            4,
        )
        decision = (
            "linked"
            if (
                lexical_similarity >= 0.55
                and deadline_compatible
                and source_compatible
                and (entity_overlap >= 2 or platform_group_match)
            )
            else "unresolved"
        )
        return {
            "decision": decision,
            "score": score,
            "matched_market_id": linked_market.id,
            "lexical_similarity": lexical_similarity,
            "normalized_time_compatible": deadline_compatible,
            "deadline_delta_hours": deadline_delta_hours,
            "resolution_source_compatible": source_compatible,
            "source_alignment": "aligned" if source_compatible else "mismatch",
            "entity_overlap": shared_tokens,
            "platform_native_key_match": platform_group_match,
            "blocking_reasons": [
                reason
                for reason, enabled in (
                    ("low lexical similarity", lexical_similarity < 0.55),
                    ("deadline mismatch", not deadline_compatible),
                    ("resolution source mismatch", not source_compatible),
                    ("insufficient entity overlap", entity_overlap < 2 and not platform_group_match),
                )
                if enabled
            ],
        }

    @staticmethod
    def _base_provenance(market) -> dict:
        return {
            "market_id": market.id,
            "platform": market.platform,
            "group_id": market.group_id,
            "identity_version": _IDENTITY_SCORER_VERSION,
        }

    @staticmethod
    def _title_tokens(title: str) -> set[str]:
        # BUG-030 Fix: Include critical 2-character entities (US, UK, EU, AI, XI, JD)
        return {
            token
            for token in re.findall(r"[a-z0-9]+", title.lower())
            if len(token) >= 3 or token in {"us", "uk", "eu", "ai", "no", "id", "xi", "jd"}
        }

    @staticmethod
    def _normalized_source(source: str | None) -> str:
        if not isinstance(source, str) or not source.strip():
            return ""
        # [LOGIC FIX L-006] Remove www. and protocols for better matching
        s = source.strip().lower()
        s = re.sub(r"^(https?://)?(www\.)?", "", s)
        return s
