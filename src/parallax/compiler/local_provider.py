import json
import logging

import httpx
from parallax.compiler.provider import CompilerProvider
from parallax.config import settings
from parallax.shared.schemas import ContractSchema, RawMarketData

logger = logging.getLogger(__name__)

class LocalLLMProvider(CompilerProvider):
    """
    OpenAI-compatible local LLM provider (vLLM, Ollama, etc.)
    Provides a fast, autonomous fallback for semantic compilation.
    """

    def __init__(self, base_url: str = "http://localhost:8000/v1"):
        self.base_url = base_url
        self.model = getattr(settings, "local_llm_model", "llama3")

    @property
    def version(self) -> str:
        return f"local-{self.model}"

    async def compile(self, market: RawMarketData) -> ContractSchema:
        prompt = self._build_prompt(market)
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a professional prediction market analyst. Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                # Parse structured output
                schema_dict = json.loads(content)
                return ContractSchema(**schema_dict)
            except Exception as e:
                logger.error(f"Local LLM compilation failed: {e}")
                raise

    def _build_prompt(self, market: RawMarketData) -> str:
        return f"""
        Extract the structured contract schema from this prediction market description:
        Market: {market.title}
        Description: {market.description}
        
        Return a JSON object with:
        - underlying_event: summary of what happens
        - outcome_type: 'binary' or 'scalar'
        - settlement_logic: brief description of how it resolves
        - expiry: approximate timestamp or 'unknown'
        """
