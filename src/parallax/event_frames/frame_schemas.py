from __future__ import annotations

from pydantic import BaseModel, Field

from parallax.shared.schemas import CanonicalEventFrameSchema


class EventFrameMembershipSchema(BaseModel):
    raw_market_id: str
    frame_id: str
    membership_type: str
    confidence: float
    evidence: dict[str, object] = Field(default_factory=dict)


__all__ = [
    "CanonicalEventFrameSchema",
    "EventFrameMembershipSchema",
]
