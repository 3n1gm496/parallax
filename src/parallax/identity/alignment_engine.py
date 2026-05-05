from __future__ import annotations

import anthropic
from pydantic import BaseModel

from parallax.config import settings
from parallax.shared.schemas import IdentityType

_SYSTEM_PROMPT = """You are a prediction-market Semantic Alignment Engine.
Given two prediction markets, determine if they are SEMANTICALLY IDENTICAL.
To be semantically identical, they must have:
1. Identical Resolution Semantics (the exact conditions under which they pay out must be logically equivalent).
2. Identical Temporal Scope (deadlines must match in intent, even if times differ slightly due to platform rules).
3. Equivalent natural language intent.

Output a JSON object with:
- "confidence": float between 0.0 and 1.0 (1.0 = perfectly identical)
- "identity_type": string (one of "same_event", "correlated", "false_equivalence", "duplicate")
- "reasoning": string explaining why.
"""

class SemanticAlignmentResult(BaseModel):
    confidence: float
    identity_type: str
    reasoning: str

class SemanticAlignmentEngine:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def align_pair(self, market_a, market_b) -> dict:
        platform_group_match = bool(
            market_a.group_id and market_b.group_id and market_a.group_id == market_b.group_id
        )
        if platform_group_match:
            return {
                "score": 1.0,
                "identity_type": IdentityType.DUPLICATE,
                "reasoning": "platform_group_match",
                "platform_group_match": True,
            }

        user_content = (
            f"Market A:\nTitle: {market_a.title}\nDeadline: {market_a.deadline}\nResolution Source: {market_a.resolution_source}\n"
            f"Market B:\nTitle: {market_b.title}\nDeadline: {market_b.deadline}\nResolution Source: {market_b.resolution_source}\n"
        )
        
        try:
            response = self._client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=[{"type": "text", "text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": user_content}],
                tools=[{
                    "name": "report_alignment",
                    "description": "Report the semantic alignment",
                    "input_schema": SemanticAlignmentResult.model_json_schema()
                }],
                tool_choice={"type": "tool", "name": "report_alignment"}
            )
            
            tool_block = next((b for b in response.content if b.type == "tool_use"), None)
            if tool_block:
                result = SemanticAlignmentResult.model_validate(tool_block.input)
                itype_str = result.identity_type.upper()
                
                # map string to enum
                valid_types = {i.value: i for i in IdentityType}
                if result.identity_type in valid_types:
                    itype = valid_types[result.identity_type]
                elif itype_str in IdentityType.__members__:
                    itype = IdentityType[itype_str]
                else:
                    itype = IdentityType.FALSE_EQUIVALENCE

                return {
                    "score": float(result.confidence),
                    "identity_type": itype,
                    "reasoning": result.reasoning,
                    "platform_group_match": False,
                }
        except Exception:
            # Fallback for testing when no Anthropic credits are available
            tokens_a = set(market_a.title.lower().split())
            tokens_b = set(market_b.title.lower().split())
            if not tokens_a or not tokens_b:
                score = 0.0
            else:
                score = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
            
            itype = IdentityType.SAME_EVENT if score > 0.4 else IdentityType.FALSE_EQUIVALENCE
            return {
                 "score": score,
                 "identity_type": itype,
                 "reasoning": "Fallback heuristic (no API credits)",
                 "platform_group_match": False,
            }
