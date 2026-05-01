from __future__ import annotations
import anthropic
from parallax.compiler.provider import CompilerProvider
from parallax.config import settings
from parallax.shared.schemas import ContractSchema, RawMarketData

_MODEL = "claude-sonnet-4-6"
_VERSION = "anthropic-sonnet-4-6-v1"

_SYSTEM_PROMPT = """You are a prediction-market contract compiler.

Given a prediction market's title, description, and resolution criteria, extract
a structured contract definition with:

- yes_conditions: exhaustive list of conditions under which the market resolves YES
- no_conditions: exhaustive list of conditions under which the market resolves NO
- exclusions: edge cases explicitly excluded from resolution
- ambiguity_terms: terms whose meaning could be disputed, with a brief description of the ambiguity
- counterexamples: scenarios where markets with similar language would resolve differently,
  identifying subtle semantic differences
- compiler_confidence: your calibrated confidence (0.0–1.0) that the contract is
  unambiguous and complete, where 1.0 means fully unambiguous

Be precise. If criteria are vague, reflect that with low confidence and flag the
ambiguous terms. Do not invent resolution rules not implied by the text."""


class AnthropicCompilerProvider(CompilerProvider):
    """Compiles prediction-market specs into ContractSchema using Claude."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key
        )

    @property
    def version(self) -> str:
        return _VERSION

    async def compile(self, market: RawMarketData) -> ContractSchema:
        user_content = (
            f"Title: {market.title}\n\n"
            f"Description: {market.description}\n\n"
            f"Resolution criteria: {market.resolution_criteria}\n\n"
            f"Outcomes: {', '.join(market.outcomes)}"
        )

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
            tools=[
                {
                    "name": "compile_contract",
                    "description": "Output the compiled prediction market contract schema.",
                    "input_schema": ContractSchema.model_json_schema(),
                }
            ],
            tool_choice={"type": "tool", "name": "compile_contract"},
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        return ContractSchema.model_validate(tool_block.input)
